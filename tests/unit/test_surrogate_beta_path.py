"""Tests de la voie β — surrogates branchés sur le solveur complet.

Vérifie :
  - run_sim_smart sans manager == sim.run (aucun overhead) ;
  - voie solveur complet : enregistrement d'échantillon + note β ;
  - voie β après entraînement : SimResult marqué β, solveur contourné ;
  - MultiPhysicsCoupling.run(surrogate_manager=...) remonte beta_kinds ;
  - extraction de la métrique phare (headline_value).
"""
from __future__ import annotations

import pytest

from services.design_core import DesignGraph
from services.simulator.base import SimResult
from services.simulator.surrogate_models.beta_path import (
    AUTOTRAIN_EVERY,
    headline_value,
    run_sim_smart,
)
from services.simulator.surrogate_models.manager import SurrogateManager
from services.simulator.thermal_sim import ThermalSim


@pytest.fixture()
def tiny_graph() -> DesignGraph:
    g = DesignGraph(project_id="beta", name="beta", board_size=(40.0, 30.0))
    g.add_component("U1", footprint="soic-8", x=10.0, y=10.0, power_w=1.0)
    g.connect("U1", "1", "PWR")
    g.place("U1", 10.0, 10.0)
    return g


def _trained_manager(tmp_path, tiny_graph) -> SurrogateManager:
    """Manager avec un surrogate thermal entraîné sur des échantillons synthétiques."""
    mgr = SurrogateManager(min_samples=8, data_root=str(tmp_path))
    res, _beta = run_sim_smart(ThermalSim(), tiny_graph, manager=mgr)
    feats = {"n_comp": 1.0, "density": 0.02, "power_sum": 1.0, "wire_length": 0.0}
    for i in range(30):
        f = dict(feats)
        f["power_sum"] = 0.5 + i * 0.05
        mgr.record("thermal", f, 25.0 + 8.0 * f["power_sum"])
    mgr.maybe_train("thermal")
    assert mgr.status["thermal"].trained
    return mgr


def test_no_manager_is_transparent(tiny_graph):
    """Sans manager, run_sim_smart délègue strictement à sim.run()."""
    result, beta_used = run_sim_smart(ThermalSim(), tiny_graph, manager=None)
    assert beta_used is False
    assert result.passed is not None
    assert "max_temp_c" in result.metrics
    assert "beta" not in result.metrics


def test_full_solver_records_sample(tmp_path, tiny_graph):
    """Sans surrogate entraîné, le solveur complet tourne et enregistre l'échantillon."""
    mgr = SurrogateManager(min_samples=8, data_root=str(tmp_path))
    result, beta_used = run_sim_smart(ThermalSim(), tiny_graph, manager=mgr)
    assert beta_used is False
    n = len(mgr.dataset("thermal").load()[1])
    assert n == 1
    assert any("surrogate" in note for note in (result.notes or []))


def test_beta_path_replaces_solver(tmp_path, tiny_graph):
    """Après entraînement, la voie β produit un SimResult marqué (solveur contourné)."""
    mgr = _trained_manager(tmp_path, tiny_graph)
    result, beta_used = run_sim_smart(ThermalSim(), tiny_graph, manager=mgr)
    assert beta_used is True
    assert result.metrics.get("beta") is True
    assert result.metrics.get("source") == "surrogate"
    assert "max_temp_c" in result.metrics
    assert result.runtime_s < 0.5  # inférence rapide (pas de grille thermique)
    assert any("β" in note for note in result.notes)


def test_coupling_reports_beta_kinds(tmp_path, tiny_graph):
    """MultiPhysicsCoupling.run exploite le manager et liste les kinds en β."""
    from services.simulator.multi_physics_loop.coupling import MultiPhysicsCoupling

    mgr = _trained_manager(tmp_path, tiny_graph)
    out = MultiPhysicsCoupling().run(tiny_graph, [ThermalSim()], surrogate_manager=mgr)
    assert "thermal" in out["beta_kinds"]
    assert out["results"]["thermal"].metrics.get("beta") is True

    # sans manager → pas de β
    out2 = MultiPhysicsCoupling().run(tiny_graph, [ThermalSim()])
    assert out2["beta_kinds"] == []


def test_headline_value_extraction():
    """headline_value extrait la métrique phare de chaque kind (repli None)."""
    assert headline_value("thermal", {"max_temp_c": 31.5}) == 31.5
    assert headline_value("si", {"worst_gamma": 0.1}) == 0.1
    assert headline_value("pi", {"worst_ir_drop_mv": 12.0}) == 12.0
    assert headline_value("thermal", {"pas_de_metrique": 1.0}) is None
    assert headline_value("inconnu", {"x": 1.0}) is None


def test_beta_result_passed_threshold():
    """Le verdict β compare la valeur prédite à la limite du simulateur."""
    from services.simulator.surrogate_models.beta_path import _beta_passed, _beta_result

    sim = ThermalSim()  # max_temp_c = 85 par défaut
    assert _beta_passed("thermal", 84.0, sim) is True
    assert _beta_passed("thermal", 90.0, sim) is False
    res = _beta_result("thermal", 40.0, 0.05, sim)
    assert isinstance(res, SimResult)
    assert res.passed is True
    assert res.metrics["latency_ms"] == 0.05


def test_autotrain_constant():
    """L'auto-entraînement périodique est raisonnable (≥ 5, ≤ 50 échantillons)."""
    assert 5 <= AUTOTRAIN_EVERY <= 50
