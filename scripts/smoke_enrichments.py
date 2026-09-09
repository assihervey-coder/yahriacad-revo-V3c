"""Smoke test des enrichissements V3+ (diff pairs, world model, surrogates, corrector)."""
import os
import sys

os.environ.setdefault("PCB3_DATA_DIR", "/tmp/pcb3_smoke")
sys.path.insert(0, ".")
sys.path.insert(0, "backend")

OK = []


def check(name, fn):
    try:
        fn()
        OK.append(name)
        print(f"  ✓ {name}")
    except Exception as exc:
        print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
        raise


def build_graph():
    from services.design_core import DesignGraph
    g = DesignGraph(project_id="smoke", name="smoke", board_size=(60.0, 40.0))
    g.add_component(ref="U1", footprint="QFN-16_0.5mm", x=10, y=20)
    g.add_component(ref="J1", footprint="USB-C_0.5mm", x=50, y=20)
    g.add_component(ref="R1", footprint="0402", x=30, y=10)
    g.add_component(ref="C1", footprint="0402", x=30, y=30)
    g.connect("U1", "A5", "USB_DP")   # paire différentielle
    g.connect("J1", "A5", "USB_DP")
    g.connect("U1", "A6", "USB_DM")
    g.connect("J1", "A6", "USB_DM")
    g.connect("U1", "VDD", "VDD")
    g.connect("C1", "1", "VDD")
    g.connect("C1", "2", "GND")
    g.connect("R1", "1", "GND")
    return g


# 1) Paires différentielles enrichies
def t_diff_pairs():
    from services.router.differential_pairs import (
        DifferentialPairRouter, PairQualityReport, find_differential_pairs)
    from services.router.geometrical import MazeRouter
    g = build_graph()
    pairs = find_differential_pairs(g)
    assert len(pairs) == 1, f"paires trouvées: {len(pairs)}"
    maze = MazeRouter(board_size=g.board_size)
    router = DifferentialPairRouter(maze=maze)
    rep = router.route_pair(g, pairs[0][0], pairs[0][1], 0.2)
    assert isinstance(rep, PairQualityReport), rep
    d = rep.to_dict()
    assert d["skew_matched"] is True or d["skew_mm"] <= 0.15 + 1e-6, d
    assert d["coupling_ratio"] > 0.2, d
    assert d["strategy"] in ("offset", "astar_fallback"), d
    print(f"    paire: skew={d['skew_mm']}mm, gap={d['min_gap_mm']}, couplage={d['coupling_ratio']*100:.0f}%, stratégie={d['strategy']}")


# 2) World model enrichi : ensemble, rollout, entraînement, attribution
def t_world_model():
    import numpy as np
    from services.ai_engine.rl_agent.world_model import WorldModel, state_from_graph
    from services.ai_engine.rl_agent.action_space import PlacementAction, PlacementActionKind
    g = build_graph()
    wm = WorldModel(seed=3, ensemble_size=3)
    s0 = state_from_graph(g)

    # transitions synthétiques : bouger vers le centre réduit le WL
    rng = np.random.default_rng(0)
    for i in range(60):
        s = state_from_graph(g)
        act = PlacementAction(kind=PlacementActionKind.MOVE, ref="R1",
                              dx=float(rng.choice([-1.0, 1.0])), dy=0.0)
        g.place("R1", 30 + (i % 5), 10, 0)
        s1 = state_from_graph(g)
        reward = -s1["wire_length"] / 100.0
        wm.record_transition(s, act, s1, reward)
    losses = wm.train(epochs=40, lr=2e-3)
    assert losses["n_transitions"] == 60
    assert losses["dyn_mse_mean"] < 1.0, losses
    assert losses["reward_mse"] < 10.0, losses

    # dynamics : incertitude présente après entraînement
    s0 = state_from_graph(g)
    act = PlacementAction(kind=PlacementActionKind.MOVE, ref="R1", dx=1.0, dy=0.0)
    s1 = wm.dynamics(s0, act)
    assert wm.last_uncertainty.get("alpha", 0) > 0
    # rollout + plan : retourne une action
    acts = [PlacementAction(kind=PlacementActionKind.MOVE, ref="R1", dx=d, dy=0.0)
            for d in (-2.0, -1.0, 0.5, 1.0, 2.0)]
    scored = wm.rollout(s0, acts, depth=2)
    assert len(scored) == len(acts) and scored[0][1] >= scored[-1][1]
    best = wm.plan(s0, acts, depth=2)
    assert best is not None
    # attribution
    attrib = wm.feature_attribution(s0)
    assert isinstance(attrib, dict)
    # récompense apprise (float fini)
    r = wm.reward_predictor(s1)
    assert np.isfinite(r)
    # compat fit_transition + save/load (format ensemble)
    f = wm.encoder(s0); f2 = wm.encoder(s1)
    wm.fit_transition(f, f2, lr=1e-3)
    wm.save("/tmp/pcb3_smoke/wm.npz")
    wm2 = WorldModel(seed=3, ensemble_size=3)
    assert wm2.load("/tmp/pcb3_smoke/wm.npz") is True
    assert wm2._dyn_trained is True
    print(f"    dyn_mse={losses['dyn_mse_mean']}, reward_mse={losses['reward_mse']}, α={wm.last_uncertainty.get('alpha'):.2f}")


# 3) Surrogates : collecte → entraînement → inférence β → benchmark
def t_surrogates():
    import numpy as np
    from services.simulator.surrogate_models import (
        FastPredictor, SurrogateDataset, SurrogateManager)
    from services.simulator.surrogate_models.dataset import _root

    ds = SurrogateDataset("thermal", root="/tmp/pcb3_smoke/ds")
    ds.clear()
    rng = np.random.default_rng(0)
    # "solveur complet" synthétique : T = 25 + 8*P*(1+0.5*d)
    for _ in range(40):
        p, d = float(rng.uniform(0.5, 4.0)), float(rng.uniform(0.1, 0.6))
        feats = {"n_comp": 12.0, "density": d, "power_sum": p, "wire_length": 90.0}
        ds.append(feats, 25.0 + 8.0 * p * (1.0 + 0.5 * d))
    assert len(ds) == 40

    mgr = SurrogateManager(min_samples=25, data_root="/tmp/pcb3_smoke/ds")
    mgr._datasets["thermal"] = ds
    st = mgr.maybe_train("thermal")
    assert st is not None and st.trained, st
    assert st.val_mae is not None and st.val_mae < 2.0, st
    assert st.r2 is not None and st.r2 > 0.9, st

    feats = {"n_comp": 12.0, "density": 0.3, "power_sum": 2.0, "wire_length": 90.0}
    out = mgr.predict_fast("thermal", feats)
    assert out["trained"] and out["beta"] is True
    assert out["latency_ms"] < 5.0, out
    truth = 25.0 + 8.0 * 2.0 * (1.0 + 0.5 * 0.3)
    assert abs(out["value"] - truth) < 3.0, (out, truth)

    # benchmark : speedup réel > 1
    bench = mgr.benchmark("thermal", feats, full_solver=lambda: (time.sleep(0.01), truth)[1])
    assert bench.speedup_x > 1.0, bench
    assert bench.abs_error < 3.0

    # FastPredictor avec manager
    g = build_graph()
    fp = FastPredictor(manager=mgr)
    preds = fp.predict(g)
    assert preds["thermal"]["source"] == "surrogate" and preds["thermal"]["beta"] is True
    assert preds["si"]["source"] == "analytic"     # pas entraîné
    # status_all pour l'API
    status = mgr.status_all()
    assert status["thermal"]["trained"] is True
    # save/load
    mgr.save("/tmp/pcb3_smoke/surrogates")
    mgr2 = SurrogateManager(data_root="/tmp/pcb3_smoke/ds")
    assert mgr2.load("/tmp/pcb3_smoke/surrogates") >= 1
    print(f"    MAE val={st.val_mae:.3f}, R²={st.r2:.3f}, latence={out['latency_ms']*1000:.0f}µs, speedup={bench.speedup_x:.0f}x")


# 4) WorldModelProposer : imagine-puis-propose
def t_world_proposer():
    from services.ai_engine.autonomous_optimizer import WorldModelProposer
    g = build_graph()
    proposer = WorldModelProposer(pool_size=20, top_k=3)
    props = proposer.propose(g, None, k=3)
    assert isinstance(props, list) and len(props) >= 1, props
    p0 = props[0]
    assert p0.kind == "move_component" and "ref" in p0.params
    assert "récompense imaginée" in p0.rationale
    assert proposer.last_imagined, "last_imagined vide"
    print(f"    top proposal: {p0.params} → {p0.rationale[:60]}")


# 5) Corrector : gate VALID + vrai optimizer + fine pitch
def t_corrector():
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent
    agent = CorrectorAgent()

    # construction du vrai optimizer
    optimizer, name = agent._build_optimizer()
    assert optimizer is not None, "optimizer non construit"
    assert "world_model" in name, name

    # garde VALID : verdict invalide → pas d'optimize direct
    ctx = {"graph": build_graph(), "verification": {"passed": False,
                                                    "self": {"passed": False, "issues": []}}}
    res = agent.execute({**ctx, "action": "optimize"})
    assert res is not None
    out = getattr(res, "output", {}) or {}
    assert out.get("engine") == "autonomous_optimizer(llm+rl+world_model)", out
    print(f"    optimizer réel: engine={out.get('engine')}, score={out.get('score')}, iters={out.get('iterations')}")

    # correction fine-pitch : créer une vraie violation de clearance entre traces
    g = build_graph()
    from shared.geometry import Point, RoutePath
    nets = g.nets
    nets["USB_DP"].path = RoutePath(net_id="USB_DP", points=[
        Point(11.0, 20.5), Point(30.0, 20.5), Point(30.0, 24.0), Point(49.0, 24.0)],
        layer=0, width_mm=0.2, vias=[])
    nets["USB_DP"].routed = True
    nets["USB_DM"].path = RoutePath(net_id="USB_DM", points=[
        Point(11.0, 20.65), Point(30.0, 20.65), Point(30.0, 18.0), Point(49.0, 18.0)],
        layer=0, width_mm=0.2, vias=[])
    nets["USB_DM"].routed = True
    before = agent._count_trace_clearance(g, {"USB_DP", "USB_DM"})
    assert before >= 1, f"aucune violation générée (before={before})"
    fixed = agent._fix_trace_clearance(g, "USB_DP", "USB_DM", {})
    after = agent._count_trace_clearance(g, {"USB_DP", "USB_DM"})
    assert after < before, f"pas d'amélioration: before={before}, after={after}"
    print(f"    fine-pitch: violations {before} → {after}, stats={agent._strategy_stats}")


import time

check("diff_pairs", t_diff_pairs)
check("world_model", t_world_model)
check("surrogates", t_surrogates)
check("world_proposer", t_world_proposer)
check("corrector", t_corrector)

print(f"\nENRICHISSEMENTS OK ({len(OK)}/5)")
