"""Schéma GraphQL — strawberry si disponible, sinon moteur JSON de repli.

Types : Design {name, revision, stats}, Agent {role, status, confidence}
Query : design(projectId), agents(projectId)
Mutation : runCommand(message)
"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from shared.utilities import get_logger

from api_gateway.deps import get_tenant, load_project_graph
from api_gateway.routes.chat import submit_chat_command
from orchestrator.common import graph_stats
from orchestrator.state_manager import ProjectState, get_agent_state_store
from orchestrator.workflow_engine.engine import WorkflowEngine  # noqa: F401 (type only)

log = get_logger("api.graphql")

router = APIRouter(tags=["graphql"])

try:  # strawberry optionnel
    import strawberry  # type: ignore

    HAS_STRAWBERRY = True
except Exception:  # pragma: no cover - environnement sans strawberry
    strawberry = None
    HAS_STRAWBERRY = False


# ---------------------------------------------------------------------------
# Résolveurs (partagés par les deux moteurs)
# ---------------------------------------------------------------------------

def _design_data(project_id: str, tenant: str = "default") -> dict[str, Any]:
    graph, revision = load_project_graph(project_id, tenant)
    if graph is None:
        return {"name": project_id, "revision": 0,
                "stats": {"components": 0, "nets": 0}, "found": False}
    name = project_id
    state = ProjectState.load(project_id, tenant)
    if state is not None:
        name = state.name
    return {"name": name, "revision": revision,
            "stats": graph_stats(graph), "found": True}


def _agents_data(project_id: str, tenant: str = "default") -> list:
    """État des 10 agents : live (agent_state) sinon registre statique."""
    live: dict[str, dict[str, Any]] = {}
    store = get_agent_state_store()
    for _task_id, roles in store._data.items():  # accès interne volontaire
        for role, entry in roles.items():
            previous = live.get(role)
            if previous is None or float(entry.get("ts", 0)) >= float(previous.get("ts", 0)):
                live[role] = {"ts": float(entry.get("ts", 0)), **entry}
    agents = []
    try:
        from api_gateway.deps import get_engine

        roles = [role.value for role in get_engine().agents]
    except Exception:
        from shared.contracts import AgentRole

        roles = [role.value for role in AgentRole]
    for role in sorted(roles):
        entry = live.get(role) or {}
        agents.append({
            "role": role,
            "status": str(entry.get("status") or "idle"),
            "confidence": float(entry.get("confidence") or 0.0),
        })
    return agents


def _run_command(message: str, tenant: str = "default", project_id: str = "") -> dict[str, Any]:
    result = submit_chat_command(message=message, project_id=project_id, tenant=tenant)
    return {"accepted": bool(result["accepted"]), "jobId": result["job_id"],
            "intent": result["intent"], "projectId": result["project_id"]}


# ---------------------------------------------------------------------------
# Moteur de repli (JSON) — queries connues parsées par regex
# ---------------------------------------------------------------------------

def execute_query(query: str, variables: dict[str, Any] | None = None,
                  tenant: str = "default") -> dict[str, Any]:
    variables = variables or {}
    for key, value in variables.items():
        query = query.replace(f"${key}", json.dumps(value) if not isinstance(value, str) else value)
    try:
        mutation = re.search(r'runCommand\s*\(\s*message\s*:\s*"([^"]*)"', query)
        if mutation and re.match(r"\s*mutation", query, re.I):
            return {"data": {"runCommand": _run_command(mutation.group(1), tenant)}}
        design = re.search(r'design\s*\(\s*projectId\s*:\s*"([^"]+)"\s*\)', query, re.I)
        if design:
            return {"data": {"design": _design_data(design.group(1), tenant)}}
        agents = re.search(r'agents\s*\(\s*projectId\s*:\s*"([^"]+)"\s*\)', query, re.I)
        if agents:
            return {"data": {"agents": _agents_data(agents.group(1), tenant)}}
        return {"errors": [{"message": "query non reconnue — supportées: design(projectId), "
                                       "agents(projectId), mutation runCommand(message)"}]}
    except Exception as exc:
        return {"errors": [{"message": str(exc)}]}


# ---------------------------------------------------------------------------
# Schéma strawberry (si la dépendance est présente)
# ---------------------------------------------------------------------------

STRAWBERRY_SCHEMA: Any = None
if HAS_STRAWBERRY:  # pragma: no cover - dépend de l'env
    try:
        @strawberry.type
        class DesignStats:  # noqa: D101
            components: int
            nets: int

        @strawberry.type
        class Design:  # noqa: D101
            name: str
            revision: int
            stats: DesignStats

        @strawberry.type
        class Agent:  # noqa: D101
            role: str
            status: str
            confidence: float

        @strawberry.type
        class Query:  # noqa: D101
            @strawberry.field
            def design(self, project_id: str) -> Design:
                data = _design_data(project_id)
                stats = data.get("stats") or {}
                return Design(name=str(data.get("name")), revision=int(data.get("revision", 0)),
                              stats=DesignStats(components=int(stats.get("components", 0)),
                                                nets=int(stats.get("nets", 0))))

            @strawberry.field
            def agents(self, project_id: str) -> list:
                return [Agent(role=a["role"], status=a["status"], confidence=a["confidence"])
                        for a in _agents_data(project_id)]

        @strawberry.type
        class Mutation:  # noqa: D101
            @strawberry.mutation
            def run_command(self, message: str) -> str:
                result = _run_command(message)
                return str(result.get("jobId", ""))

        STRAWBERRY_SCHEMA = strawberry.Schema(query=Query, mutation=Mutation)
    except Exception:
        STRAWBERRY_SCHEMA = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/graphql")
async def graphql_post(request: Request) -> JSONResponse:
    """Endpoint GraphQL (POST) — strawberry si dispo, sinon moteur JSON."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    query = str(body.get("query") or "")
    variables = body.get("variables") or {}
    tenant = get_tenant(request)
    if STRAWBERRY_SCHEMA is not None:
        try:
            result = STRAWBERRY_SCHEMA.execute_sync(query, variable_values=variables)
            payload: dict[str, Any] = {}
            if result.errors:
                payload["errors"] = [{"message": str(error)} for error in result.errors]
            if result.data is not None:
                payload["data"] = result.data
            return JSONResponse(payload)
        except Exception as exc:
            return JSONResponse({"errors": [{"message": str(exc)}]}, status_code=400)
    return JSONResponse(execute_query(query, variables, tenant))


@router.get("/graphql")
async def graphql_get() -> dict[str, Any]:
    """Description de l'endpoint GraphQL."""
    return {
        "graphql": "ready",
        "engine": "strawberry" if STRAWBERRY_SCHEMA is not None else "fallback-json",
        "queries": ["design(projectId: \"...\") { name revision stats { components nets } }",
                    "agents(projectId: \"...\") { role status confidence }"],
        "mutations": ["runCommand(message: \"...\")"],
        "transport": "POST /graphql {\"query\": \"...\", \"variables\": {}}",
    }
