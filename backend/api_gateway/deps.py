"""Dépendances FastAPI — tenant, orchestrator LLM, versioning, moteur."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from shared.utilities import get_logger, get_settings

from orchestrator.common import call_probe, extract_rev, get_field, try_import
from orchestrator.workflow_engine.engine import WorkflowEngine

log = get_logger("api.deps")

_ORCHESTRATOR: Any = None
_ENGINE: WorkflowEngine | None = None
_VERSIONINGS: dict[str, Any] = {}


def get_tenant(request: Request) -> str:
    """Tenant courant (injecté par le middleware tenant, sinon header/default)."""
    tenant = getattr(request.state, "tenant", None)
    if tenant:
        return str(tenant)
    return request.headers.get("x-tenant-id", "default") or "default"


def get_user_id(request: Request) -> str:
    """Utilisateur courant (JWT en prod, 'anon' en dev)."""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("user"):
        return str(user["user"])
    return "default"


def get_orchestrator() -> Any:
    """Singleton LLMOrchestrator (None si services.ai_engine absent)."""
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        cls = try_import("services.ai_engine", ["LLMOrchestrator"]).get("LLMOrchestrator")
        if cls is None:
            return None
        try:
            _ORCHESTRATOR = cls()
        except TypeError:
            try:
                _ORCHESTRATOR = cls(model=get_settings().llm_model)
            except Exception:
                _ORCHESTRATOR = None
    return _ORCHESTRATOR


def get_versioning(project_id: str) -> Any:
    """DesignVersioning par projet (mis en cache, None si design_core absent)."""
    if not project_id:
        return None
    if project_id not in _VERSIONINGS:
        cls = try_import("services.design_core", ["DesignVersioning"]).get("DesignVersioning")
        versioning = None
        if cls is not None:
            try:
                versioning = cls(project_id)
            except TypeError:
                try:
                    versioning = cls()
                except Exception:
                    versioning = None
        _VERSIONINGS[project_id] = versioning
    return _VERSIONINGS[project_id]


def get_engine() -> WorkflowEngine:
    """Singleton WorkflowEngine (agents instanciés une fois)."""
    global _ENGINE
    if _ENGINE is None:
        from orchestrator.agent_pipeline import build_agents

        _ENGINE = WorkflowEngine(agents=build_agents(orchestrator=get_orchestrator()))
    return _ENGINE


def load_project_graph(project_id: str, tenant: str = "default",
                       user: str = "default") -> tuple[Any, int]:
    """Graphe courant d'un projet : état persisté, sinon versioning.current()."""
    from orchestrator.state_manager import DesignStateManager

    if not project_id:
        return None, 0
    try:
        loaded = DesignStateManager().load_design(tenant, user, project_id)
        if loaded is not None:
            return loaded
    except Exception:
        log.debug("chargement design persisté impossible", exc_info=True)
    versioning = get_versioning(project_id)
    if versioning is not None:
        try:
            current = call_probe(versioning, "current")
            if current is not None:
                if isinstance(current, tuple) and len(current) == 2:
                    return current[0], int(current[1] or 0)
                if get_field(current, "components", default=None) is not None:
                    return current, extract_rev(current) or 0
        except Exception:
            log.debug("versioning.current() indisponible", exc_info=True)
    return None, 0
