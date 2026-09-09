"""Route projets — CRUD + arborescence data/projects/{tenant}/..."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shared.utilities import get_logger

from api_gateway.deps import get_tenant, get_user_id
from api_gateway.middleware.tenant import safe_path_segment
from orchestrator.state_manager import DesignStateManager, ProjectState

log = get_logger("api.projects")

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    tenant_id: str = "default"
    user_id: str = "default"


@router.post("", status_code=201)
async def create_project(payload: ProjectCreate, request: Request) -> dict[str, Any]:
    """Crée le projet + son arborescence (design, jobs, exports, simulations)."""
    tenant = safe_path_segment(get_tenant(request) if payload.tenant_id == "default" else payload.tenant_id)
    user = safe_path_segment(payload.user_id if payload.user_id != "default" else get_user_id(request))
    state = ProjectState.create(payload.name, tenant_id=tenant, user_id=user)
    return {"project_id": state.project_id, "name": state.name,
            "tenant_id": state.tenant_id, "user_id": state.user_id,
            "last_rev": state.last_rev, "status": state.status}


@router.get("")
async def list_projects(request: Request,
                        tenant: str = "") -> dict[str, Any]:
    """Liste les projets d'un tenant."""
    tenant_id = safe_path_segment(tenant or get_tenant(request))
    projects: list[dict[str, Any]] = [p.to_dict() for p in ProjectState.list_projects(tenant_id)]
    return {"tenant_id": tenant_id, "count": len(projects), "projects": projects}


@router.get("/{project_id}")
async def get_project(project_id: str, request: Request) -> dict[str, Any]:
    """État du projet + révision courante du design."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = (ProjectState.load(project_id, tenant, user)
             or ProjectState.load(project_id, tenant, "default"))
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    manager = DesignStateManager()
    history = manager.history(state.tenant_id, state.user_id, state.project_id)
    last_rev = history[-1] if history else state.last_rev
    payload = state.to_dict()
    payload["revisions"] = history
    payload["last_rev"] = max(last_rev, state.last_rev)
    return payload


@router.delete("/{project_id}")
async def delete_project(project_id: str, request: Request) -> dict[str, Any]:
    """Supprime le projet et son arborescence."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = ProjectState.load(project_id, tenant, user) or ProjectState.load(project_id, tenant, "default")
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    removed = ProjectState.delete(state.project_id, state.tenant_id, state.user_id)
    return {"deleted": removed, "project_id": state.project_id}
