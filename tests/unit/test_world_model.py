"""Tests du World Model enrichi : ensemble, incertitude, rollout, attribution."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "backend")]

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from services.ai_engine.rl_agent.action_space import (  # noqa: E402
    PlacementAction,
    PlacementActionKind,
)
from services.ai_engine.rl_agent.world_model import (  # noqa: E402
    FEATURE_DIM,
    WorldModel,
    state_from_graph,
)


@pytest.fixture
def graph():
    from services.design_core import DesignGraph  # noqa: E402

    g = DesignGraph(project_id="t", name="t", board_size=(60.0, 40.0))
    g.add_component(ref="U1", footprint="QFN-16_0.5mm", x=10, y=20)
    g.add_component(ref="R1", footprint="0402", x=30, y=10)
    g.add_component(ref="C1", footprint="0402", x=30, y=30)
    g.connect("U1", "A5", "VDD")
    g.connect("R1", "1", "VDD")
    g.connect("R1", "2", "GND")
    g.connect("C1", "1", "GND")
    return g


def _mk_move(ref="R1", dx=1.0, dy=0.0):
    return PlacementAction(kind=PlacementActionKind.MOVE, ref=ref, dx=dx, dy=dy)


def test_encoder_dimension(graph):
    wm = WorldModel(seed=1)
    f = wm.encoder(state_from_graph(graph))
    assert f.shape == (FEATURE_DIM,)
    assert np.all(np.isfinite(f))


def test_dynamics_heuristique_sans_entrainement(graph):
    wm = WorldModel(seed=1)
    s0 = state_from_graph(graph)
    s1 = wm.dynamics(s0, _mk_move())
    assert s1["wire_length"] >= 0.0
    assert wm.last_uncertainty.get("alpha", 0.0) == 0.0   # pas encore appris


def test_record_transition_et_train(graph):
    wm = WorldModel(seed=2, ensemble_size=3)
    rng = np.random.default_rng(0)
    for i in range(40):
        s = state_from_graph(graph)
        act = _mk_move(dx=float(rng.choice([-1.0, 1.0])))
        graph.place("R1", 30 + (i % 5), 10, 0)
        s1 = state_from_graph(graph)
        wm.record_transition(s, act, s1, reward=-s1["wire_length"] / 100.0)
    losses = wm.train(epochs=30)
    assert losses["n_transitions"] == 40
    assert losses["dyn_mse_mean"] < 1.0
    assert "reward_mse" in losses
    assert wm._dyn_trained and wm._reward_trained


def test_incertitude_epistemique_apres_train(graph):
    wm = WorldModel(seed=2, ensemble_size=3)
    rng = np.random.default_rng(0)
    for i in range(40):
        s = state_from_graph(graph)
        act = _mk_move(dx=float(rng.choice([-1.0, 1.0])))
        graph.place("R1", 30 + (i % 5), 10, 0)
        wm.record_transition(s, act, state_from_graph(graph), reward=-0.5)
    wm.train(epochs=30)
    wm.dynamics(state_from_graph(graph), _mk_move())
    assert wm.last_uncertainty["alpha"] > 0.0
    assert "max_std" in wm.last_uncertainty


def test_rollout_et_plan(graph):
    wm = WorldModel(seed=3)
    acts = [_mk_move(dx=d) for d in (-2.0, -1.0, 0.5, 1.0, 2.0)]
    scored = wm.rollout(state_from_graph(graph), acts, depth=2)
    assert len(scored) == len(acts)
    valeurs = [v for _, v in scored]
    assert valeurs == sorted(valeurs, reverse=True)
    best = wm.plan(state_from_graph(graph), acts, depth=2)
    assert best is not None


def test_feature_attribution_somme_un(graph):
    wm = WorldModel(seed=4)
    rng = np.random.default_rng(1)
    for i in range(30):
        s = state_from_graph(graph)
        act = _mk_move(dx=float(rng.uniform(-1, 1)))
        graph.place("R1", 29 + (i % 4), 10, 0)
        wm.record_transition(s, act, state_from_graph(graph),
                             reward=float(rng.uniform(-2, 0)))
    wm.train(epochs=30)
    attrib = wm.feature_attribution(state_from_graph(graph))
    assert isinstance(attrib, dict) and len(attrib) > 0
    assert abs(sum(attrib.values()) - 1.0) < 0.2      # normalisation approx


def test_save_load_roundtrip(graph, tmp_path):
    wm = WorldModel(seed=5, ensemble_size=2)
    for i in range(20):
        s = state_from_graph(graph)
        act = _mk_move(dx=0.5)
        graph.place("R1", 29 + (i % 4), 10, 0)
        wm.record_transition(s, act, state_from_graph(graph), reward=-1.0)
    wm.train(epochs=20)
    path = str(tmp_path / "wm.npz")
    wm.save(path)
    wm2 = WorldModel(seed=5, ensemble_size=2)
    assert wm2.load(path) is True
    assert wm2._dyn_trained is True
    f1 = wm.reward_predictor(state_from_graph(graph))
    f2 = wm2.reward_predictor(state_from_graph(graph))
    assert abs(f1 - f2) < 1e-6


def test_compat_fit_transition_lineaire(graph):
    wm = WorldModel(seed=6)
    f = wm.encoder(state_from_graph(graph))
    mse = wm.fit_transition(f, f * 0.5, lr=1e-3)
    assert mse >= 0.0
