"""Tests du WorldModelProposer et du corrector enrichi (fine-pitch, VALID gate)."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "backend")]

import pytest  # noqa: E402
from shared.geometry import Point, RoutePath  # noqa: E402


@pytest.fixture
def usb_graph():
    from services.design_core import DesignGraph  # noqa: E402

    g = DesignGraph(project_id="t", name="t", board_size=(60.0, 40.0))
    g.add_component(ref="U1", footprint="QFN-16_0.5mm", x=10, y=20)
    g.add_component(ref="J1", footprint="USB-C_0.5mm", x=50, y=20)
    g.add_component(ref="R1", footprint="0402", x=30, y=10)
    g.add_component(ref="C1", footprint="0402", x=30, y=30)
    g.connect("U1", "A5", "USB_DP")
    g.connect("J1", "A5", "USB_DP")
    g.connect("U1", "A6", "USB_DM")
    g.connect("J1", "A6", "USB_DM")
    g.connect("U1", "VDD", "VDD")
    g.connect("C1", "1", "VDD")
    g.connect("C1", "2", "GND")
    g.connect("R1", "1", "GND")
    return g


# ------------------------------------------------------------- WorldModelProposer
def test_world_proposer_propose_worldclass(usb_graph):
    from services.ai_engine.autonomous_optimizer import WorldModelProposer  # noqa: E402

    proposer = WorldModelProposer(pool_size=20, top_k=3)
    props = proposer.propose(usb_graph, None, k=3)
    assert 1 <= len(props) <= 3
    p0 = props[0]
    assert p0.kind == "move_component"
    assert "ref" in p0.params and "dx" in p0.params
    assert "récompense imaginée" in p0.rationale
    assert proposer.last_imagined, "last_imagined devrait contenir le top-k"


def test_world_proposer_graphe_vide():
    from services.ai_engine.autonomous_optimizer import WorldModelProposer  # noqa: E402
    from services.design_core import DesignGraph  # noqa: E402

    g = DesignGraph(project_id="t", name="t", board_size=(60.0, 40.0))
    proposer = WorldModelProposer()
    assert proposer.propose(g, None, k=3) == []


# --------------------------------------------------------------------- corrector
def test_build_optimizer_reel():
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent  # noqa: E402

    agent = CorrectorAgent()
    optimizer, name = agent._build_optimizer()
    assert optimizer is not None
    assert "world_model" in name


def test_valid_gate_corrige_avant_optimiser(usb_graph):
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent  # noqa: E402

    agent = CorrectorAgent()
    ctx = {
        "graph": usb_graph,
        "action": "optimize",
        "verification": {"passed": False,
                         "self": {"passed": False, "issues": []}},
    }
    res = agent.execute(ctx)
    out = getattr(res, "output", {}) or {}
    # le verdict INVALID déclenche la correction puis l'optimisation réelle
    assert out.get("engine") == "autonomous_optimizer(llm+rl+world_model)"


def test_fine_pitch_correction_reduit_violations(usb_graph):
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent  # noqa: E402

    nets = usb_graph.nets
    nets["USB_DP"].path = RoutePath(net_id="USB_DP", points=[
        Point(11.0, 20.5), Point(30.0, 20.5), Point(30.0, 24.0), Point(49.0, 24.0)],
        layer=0, width_mm=0.2, vias=[])
    nets["USB_DP"].routed = True
    nets["USB_DM"].path = RoutePath(net_id="USB_DM", points=[
        Point(11.0, 20.65), Point(30.0, 20.65), Point(30.0, 18.0), Point(49.0, 18.0)],
        layer=0, width_mm=0.2, vias=[])
    nets["USB_DM"].routed = True

    agent = CorrectorAgent()
    before = agent._count_trace_clearance(usb_graph, {"USB_DP", "USB_DM"})
    assert before >= 1
    fixed = agent._fix_trace_clearance(usb_graph, "USB_DP", "USB_DM", {})
    after = agent._count_trace_clearance(usb_graph, {"USB_DP", "USB_DM"})
    assert fixed is True
    assert after < before
    assert agent._strategy_stats.get("neckdown_reroute", 0) >= 1


def test_net_fine_pitch_detection(usb_graph):
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent  # noqa: E402

    agent = CorrectorAgent()
    assert agent._net_is_fine_pitch(usb_graph, "USB_DP") is True
