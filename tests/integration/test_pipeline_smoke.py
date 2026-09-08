"""Tests d'intégration — WorkflowEngine sur le pipeline dfm_only (smoke).

Petit DesignGraph réel : verify_all (VALIDATOR) puis analyze_and_package
(MANUFACTURING) doivent aboutir à un job completed.
"""
from __future__ import annotations

from orchestrator.workflow_engine.engine import WorkflowEngine
from orchestrator.workflow_engine.tasks import TaskSpec
from services.design_core import DesignGraph


def _graphe_smoke() -> DesignGraph:
    graph = DesignGraph(project_id="smoke-dfm", name="smoke", board_size=(40.0, 30.0))
    graph.add_component("R1", value="10k", footprint="0603", x=10.0, y=10.0, placed=True)
    graph.add_component("C1", value="100n", footprint="0603", x=25.0, y=10.0, placed=True)
    graph.add_net(name="SIG")
    graph.connect("R1", "1", "N1")
    graph.connect("C1", "1", "N1")
    return graph


def test_pipeline_dfm_only_complet() -> None:
    engine = WorkflowEngine()
    task = TaskSpec(pipeline_name="dfm_only",
                    params={"graph": _graphe_smoke()},
                    project_id="smoke-dfm")
    job = engine.run_pipeline(task)

    assert job.status == "completed"
    assert job.state["completed_steps"] == ["verify", "manufacture"]
    stats = job.state["graph_stats"]
    assert stats["components"] == 2
    assert stats["nets"] == 1


def test_pipeline_inconnu_echoue_proprement() -> None:
    engine = WorkflowEngine()
    task = TaskSpec(pipeline_name="pipeline_fantome",
                    params={"graph": _graphe_smoke()},
                    project_id="smoke-dfm")
    job = engine.run_pipeline(task)

    assert job.status == "failed"
    assert "pipeline inconnu" in job.state["error"]
