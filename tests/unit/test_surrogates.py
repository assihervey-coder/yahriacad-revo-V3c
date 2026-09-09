"""Tests des surrogates neuronaux β : dataset, manager, benchmark, FastPredictor."""
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "backend")]

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from services.simulator.surrogate_models import (  # noqa: E402
    FastPredictor,
    NeuralSurrogate,
    SurrogateDataset,
    SurrogateManager,
)


@pytest.fixture
def thermal_data(tmp_path):
    ds = SurrogateDataset("thermal", root=str(tmp_path / "ds"))
    rng = np.random.default_rng(0)
    for _ in range(40):
        p, d = float(rng.uniform(0.5, 4.0)), float(rng.uniform(0.1, 0.6))
        feats = {"n_comp": 12.0, "density": d, "power_sum": p, "wire_length": 90.0}
        ds.append(feats, 25.0 + 8.0 * p * (1.0 + 0.5 * d))
    return ds


def test_dataset_roundtrip(thermal_data):
    feats, values = thermal_data.load()
    assert len(feats) == 40 and len(values) == 40
    assert set(feats[0].keys()) == {"n_comp", "density", "power_sum", "wire_length"}
    assert len(thermal_data) == 40
    thermal_data.clear()
    assert len(thermal_data) == 0


def test_neural_surrogate_fit_predict(thermal_data):
    feats, values = thermal_data.load()
    X = np.array([[f["n_comp"], f["density"], f["power_sum"], f["wire_length"]]
                  for f in feats])
    y = np.array(values)
    s = NeuralSurrogate(name="t", n_inputs=4, n_hidden=16)
    s.fit(X, y, epochs=400, lr=3e-3)
    pred = s.predict(X)
    mae = float(np.mean(np.abs(pred - y)))
    assert mae < 1.5, mae
    assert s.trained is True
    assert len(s.loss_history) > 0
    assert s.loss_history[-1] <= s.loss_history[0] + 1e-9


def test_manager_maybe_train_et_predict_fast(thermal_data, tmp_path):
    mgr = SurrogateManager(min_samples=25, data_root=str(tmp_path / "ds"))
    mgr._datasets["thermal"] = thermal_data
    st = mgr.maybe_train("thermal")
    assert st is not None and st.trained
    assert st.val_mae is not None and st.val_mae < 2.0
    assert st.r2 is not None and st.r2 > 0.85

    feats = {"n_comp": 12.0, "density": 0.3, "power_sum": 2.0, "wire_length": 90.0}
    out = mgr.predict_fast("thermal", feats)
    assert out["trained"] is True and out["beta"] is True
    assert out["latency_ms"] < 10.0
    truth = 25.0 + 8.0 * 2.0 * (1.0 + 0.5 * 0.3)
    assert abs(out["value"] - truth) < 3.0


def test_manager_pas_assez_de_donnees(tmp_path):
    mgr = SurrogateManager(min_samples=100, data_root=str(tmp_path / "ds"))
    ds = SurrogateDataset("si", root=str(tmp_path / "ds"))
    ds.append({"n_comp": 1, "density": 0.2, "power_sum": 1.0, "wire_length": 10.0}, 0.1)
    mgr._datasets["si"] = ds
    assert mgr.maybe_train("si") is None
    out = mgr.predict_fast("si", {"n_comp": 1, "density": 0.2,
                                  "power_sum": 1.0, "wire_length": 10.0})
    assert out["trained"] is False


def test_benchmark_speedup_reel(thermal_data, tmp_path):
    mgr = SurrogateManager(min_samples=25, data_root=str(tmp_path / "ds"))
    mgr._datasets["thermal"] = thermal_data
    mgr.maybe_train("thermal")
    feats = {"n_comp": 12.0, "density": 0.3, "power_sum": 2.0, "wire_length": 90.0}
    n_before = len(thermal_data)

    def full_solver():
        time.sleep(0.01)                      # solveur "lent"
        return 25.0 + 8.0 * 2.0 * (1.0 + 0.5 * 0.3)

    bench = mgr.benchmark("thermal", feats, full_solver)
    assert bench is not None
    assert bench.speedup_x > 5.0
    assert bench.abs_error < 3.0
    assert len(thermal_data) == n_before + 1  # l'échantillon du benchmark est récolté


def test_fast_predictor_priorite_manager(thermal_data, tmp_path):
    mgr = SurrogateManager(min_samples=25, data_root=str(tmp_path / "ds"))
    mgr._datasets["thermal"] = thermal_data
    mgr.maybe_train("thermal")
    from services.design_core import DesignGraph  # noqa: E402

    g = DesignGraph(project_id="t", name="t", board_size=(60.0, 40.0))
    g.add_component(ref="U1", footprint="QFN-16_0.5mm", x=10, y=20, power_w=2.0)
    g.add_component(ref="R1", footprint="0402", x=30, y=10, power_w=0.1)
    g.connect("U1", "A5", "VDD")
    g.connect("R1", "1", "VDD")
    fp = FastPredictor(manager=mgr)
    preds = fp.predict(g)
    assert preds["thermal"]["source"] == "surrogate"
    assert preds["thermal"]["beta"] is True
    assert "latency_ms" in preds["thermal"]
    assert preds["si"]["source"] == "analytic"     # surrogate non entraîné


def test_manager_save_load(thermal_data, tmp_path):
    mgr = SurrogateManager(min_samples=25, data_root=str(tmp_path / "ds"))
    mgr._datasets["thermal"] = thermal_data
    mgr.maybe_train("thermal")
    save_dir = tmp_path / "models"
    mgr.save(str(save_dir))
    mgr2 = SurrogateManager(data_root=str(tmp_path / "ds"))
    loaded = mgr2.load(str(save_dir))
    assert loaded >= 1
    feats = {"n_comp": 12.0, "density": 0.3, "power_sum": 2.0, "wire_length": 90.0}
    out1 = mgr.predict_fast("thermal", feats)["value"]
    out2 = mgr2.predict_fast("thermal", feats)["value"]
    assert abs(out1 - out2) < 1e-6
