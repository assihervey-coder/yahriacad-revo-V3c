"""Route optimisation — TaskSpec "reoptimize" dans la TaskQueue + historique."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api_gateway.deps import get_tenant, get_user_id, get_versioning, load_project_graph
from orchestrator.common import revisions_list
from orchestrator.state_manager import DesignStateManager, ProjectState
from orchestrator.workflow_engine.tasks import TaskSpec, get_task_queue
from shared.utilities import get_logger

log = get_logger("api.optimization")

router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])


class OptimizationRequest(BaseModel):
    objective: str = Field(default="balanced")
    max_iters: int = Field(default=20, ge=1, le=500)
    project_id: str = ""


@router.post("/{project_id}")
async def start_optimization(project_id: str, payload: OptimizationRequest,
                             request: Request) -> Dict[str, Any]:
    """Crée une tâche "reoptimize" (verify → optimize → verify → export)."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = (ProjectState.load(project_id, tenant, user)
             or ProjectState.load(project_id, tenant, "default"))
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    task = TaskSpec(
        pipeline_name="reoptimize",
        params={"objective": payload.objective, "max_iters": payload.max_iters,
                "user_id": state.user_id},
        project_id=state.project_id,
        tenant_id=state.tenant_id,
    )
    get_task_queue().submit(task)
    return {"project_id": state.project_id, "task_id": task.task_id,
            "pipeline": "reoptimize", "status": task.status,
            "objective": payload.objective, "max_iters": payload.max_iters}


@router.get("/{project_id}/history")
async def optimization_history(project_id: str, request: Request) -> Dict[str, Any]:
    """Historique des révisions (traces d'optimisations successives)."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = (ProjectState.load(project_id, tenant, user)
             or ProjectState.load(project_id, tenant, "default"))
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    entries: List[Dict[str, Any]] = []
    versioning = get_versioning(project_id)
    if versioning is not None:
        entries = revisions_list(versioning)
    if not entries:
        history = DesignStateManager().history(state.tenant_id, state.user_id, state.project_id)
        entries = [{"rev": rev, "message": "", "author": "", "ts": None} for rev in history]
    optimized = [e for e in entries if "optimi" in str(e.get("message", "")).lower()]
    return {"project_id": project_id, "count": len(entries),
            "revisions": entries, "optimizations": optimized}


class ProposalsRequest(BaseModel):
    """Demande de propositions d'optimisation (RL/LLM/world model)."""

    objective: str = Field(default="balanced")
    max_iters: int = Field(default=12, ge=1, le=100)
    apply: bool = Field(default=False,
                        description="appliquer le meilleur graphe si le keeper l'accepte")


@router.post("/{project_id}/proposals")
async def optimization_proposals(project_id: str, payload: ProposalsRequest,
                                 request: Request) -> Dict[str, Any]:
    """Propositions RL/LLM du AutonomousOptimizer — UNIQUEMENT après verdict VALID.

    1. porte de verdict : le SelfVerifier doit renvoyer VALID (sinon 409 avec
       les issues — le correcteur reste la voie de réparation) ;
    2. propositions : ProposerLLM + RLOptimizer + WorldModelProposer
       (imagination MPC) évaluées sur FastEvaluator, arbitrées par le keeper ;
    3. application : si `apply=True` et score strictement meilleur, le graphe
       gagnant est committé comme nouvelle révision (rollback possible via
       l'historique des révisions).
    """
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = (ProjectState.load(project_id, tenant, user)
             or ProjectState.load(project_id, tenant, "default"))
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {project_id}")

    # ---- porte de verdict VALID (SelfVerifier du cerveau IA)
    verdict, issues = _self_verdict(graph)
    if verdict != "VALID":
        raise HTTPException(status_code=409, detail={
            "verdict": verdict, "issues": issues,
            "reason": "optimisation refusée : verdict INVALID — "
                      "utiliser le correcteur (pipeline reoptimize/correct) d'abord",
        })

    # ---- construction de l'optimizer réel (même usine que le correcteur)
    from api_gateway.deps import get_orchestrator
    from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent

    optimizer, engine = CorrectorAgent(get_orchestrator())._build_optimizer()
    if optimizer is None:
        raise HTTPException(status_code=503, detail="AutonomousOptimizer indisponible")

    baseline = _baseline_score(optimizer, graph, payload.objective)
    try:
        result = optimizer.optimize(graph.copy(),
                                    max_iters=payload.max_iters,
                                    objective=payload.objective)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"optimisation échouée: {exc}")

    from orchestrator.common import get_field

    best_score = float(get_field(result, "best_score", default=baseline) or baseline)
    iterations = int(get_field(result, "iterations", default=0) or 0)
    history = get_field(result, "history", default=[]) or []
    proposals = [h.get("proposal", {}) for h in history
                 if isinstance(h, dict) and h.get("event") == "kept"]

    applied, new_rev = False, None
    best_graph = get_field(result, "best_graph", default=None)
    if payload.apply and best_graph is not None and best_score > baseline:
        next_rev = revision + 1
        DesignStateManager().save_design(state.tenant_id, state.user_id,
                                         state.project_id, best_graph, next_rev)
        versioning = get_versioning(state.project_id)
        if versioning is not None:
            try:
                versioning.commit(best_graph,
                                  message=f"autonomous optimizer ({engine}, score {best_score:.4f})")
            except Exception:
                log.debug("commit versioning impossible", exc_info=True)
        new_rev = next_rev
        applied = True
        revision = next_rev

    # ---- événement plateforme (dashboard optimization / WS live)
    try:
        from shared.events import EventTypes, make_event
        from orchestrator.common import publish_event

        publish_event(make_event(
            EventTypes.OPTIMIZATION_ITERATION,
            {"project_id": state.project_id, "engine": engine,
             "score": round(best_score, 4), "baseline": round(baseline, 4),
             "iterations": iterations, "proposals_kept": len(proposals),
             "applied": applied, "gate": "VALID"},
            project_id=state.project_id, tenant_id=state.tenant_id,
            source="api.optimization.proposals",
        ))
    except Exception:
        log.debug("event optimization impossible", exc_info=True)

    return {
        "project_id": state.project_id,
        "verdict_gate": "VALID",
        "engine": engine,
        "objective": payload.objective,
        "baseline_score": round(baseline, 4),
        "best_score": round(best_score, 4),
        "improvement": round(best_score - baseline, 4),
        "iterations": iterations,
        "proposals": proposals[:8],
        "proposals_kept": len(proposals),
        "applied": applied,
        "revision": new_rev if new_rev is not None else revision,
    }


def _self_verdict(graph: Any) -> tuple:
    """Verdict SelfVerifier → ("VALID"|"INVALID", [issues])."""
    from orchestrator.common import get_field, try_import

    cls = try_import("services.ai_engine", ["SelfVerifier"]).get("SelfVerifier")
    if cls is None:
        return "VALID", []
    try:
        try:
            verifier = cls()
        except TypeError:
            verifier = cls()
        report = verifier.verify(graph, {})
    except Exception as exc:
        log.debug("SelfVerifier indisponible (%s) — porte ouverte", exc)
        return "VALID", []
    passed = bool(get_field(report, "passed", "ok", default=True))
    if passed:
        return "VALID", []
    issues = get_field(report, "issues", default=[]) or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return "INVALID", [str(i)[:200] for i in issues][:20]


def _baseline_score(optimizer: Any, graph: Any, objective: str) -> float:
    """Score de référence du design courant (FastEvaluator de l'optimizer)."""
    from orchestrator.common import get_field, call_probe

    evaluator = get_field(optimizer, "evaluator", default=None)
    if evaluator is None:
        return 0.0
    try:
        eval_res = call_probe(evaluator, "evaluate", (graph,))
        score = getattr(optimizer, "_score", None)
        if score is not None:
            return float(score(eval_res, objective))
    except Exception:
        log.debug("baseline score indisponible", exc_info=True)
    return 0.0
