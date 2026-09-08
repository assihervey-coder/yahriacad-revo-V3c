"""Route optimisation — TaskSpec "reoptimize" dans la TaskQueue + historique."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api_gateway.deps import get_tenant, get_user_id, get_versioning
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
