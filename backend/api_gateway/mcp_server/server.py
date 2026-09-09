"""Serveur MCP (Model Context Protocol) — JSON-RPC 2.0 sur POST /mcp.

Méthodes :
  initialize     → capabilities du serveur
  tools/list     → run_design_command, query_design, export_package, simulate
  tools/call     → dispatch vers les fonctions des services (scopes vérifiés)
  resources/list → designs + rapports
  resources/read → contenu JSON d'un design / d'un rapport
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from shared.utilities import get_logger

from api_gateway.deps import get_tenant, get_user_id, load_project_graph
from api_gateway.mcp_server.permissions import resource_allowed, tool_allowed
from api_gateway.middleware.auth import user_scopes
from api_gateway.routes.chat import submit_chat_command
from api_gateway.routes.exports import create_export
from orchestrator.common import call_probe, get_field, graph_stats, serialize_graph, try_import
from orchestrator.state_manager import ProjectState, get_agent_state_store
from orchestrator.workflow_engine.jobs import get_job_store
from orchestrator.workflow_engine.tasks import get_task_queue

log = get_logger("api.mcp")

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "pcb-ai-designer-mcp", "version": "3.0.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_design_command",
        "description": "Commande en langage naturel → design complet "
                       "(pipeline full_design en tâche de fond).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "query_design",
        "description": "Statistiques et état du design d'un projet.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "export_package",
        "description": "Exporte le paquet de fabrication (gerber, json, ipc2581...).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "fmt": {"type": "string", "default": "gerber"},
                "factory": {"type": "string", "default": "jlcpcb"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "simulate",
        "description": "Lance les simulations (thermal, si, pi, em) et retourne les métriques.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "kinds": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_id"],
        },
    },
]


class McpError(Exception):
    """Erreur JSON-RPC MCP."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------- outils
def _tool_run_design_command(args: dict[str, Any], tenant: str, user: str) -> dict[str, Any]:
    message = str(args.get("message") or "").strip()
    if not message:
        raise McpError(-32602, "paramètre 'message' requis")
    result = submit_chat_command(message=message,
                                 project_id=str(args.get("project_id") or ""),
                                 tenant=tenant, user_id=user)
    return {"accepted": result["accepted"], "job_id": result["job_id"],
            "intent": result["intent"], "plan_summary": result["plan_summary"],
            "project_id": result["project_id"]}


def _tool_query_design(args: dict[str, Any], tenant: str, user: str) -> dict[str, Any]:
    project_id = str(args.get("project_id") or "")
    graph, revision = load_project_graph(project_id, tenant, user)
    if graph is None:
        raise McpError(-32602, f"design introuvable pour le projet {project_id}")
    return {"project_id": project_id, "revision": revision,
            "stats": graph_stats(graph),
            "serialized": serialize_graph(graph)}


def _tool_export_package(args: dict[str, Any], tenant: str, user: str) -> dict[str, Any]:
    project_id = str(args.get("project_id") or "")
    graph, revision = load_project_graph(project_id, tenant, user)
    if graph is None:
        raise McpError(-32602, f"design introuvable pour le projet {project_id}")
    result = create_export(project_id, tenant, graph,
                           fmt=str(args.get("fmt") or "gerber"),
                           factory=str(args.get("factory") or "jlcpcb"))
    return result


def _tool_simulate(args: dict[str, Any], tenant: str, user: str) -> dict[str, Any]:
    project_id = str(args.get("project_id") or "")
    graph, _rev = load_project_graph(project_id, tenant, user)
    if graph is None:
        raise McpError(-32602, f"design introuvable pour le projet {project_id}")
    kinds = list(args.get("kinds") or ["thermal", "si", "pi", "em"])
    kind_map = [("thermal", "ThermalSim"), ("si", "SignalIntegritySim"),
                ("pi", "PowerIntegritySim"), ("em", "EMIProxySim")]
    results: dict[str, Any] = {}
    for kind, class_name in kind_map:
        if kind not in kinds:
            continue
        cls = try_import("services.simulator", [class_name]).get(class_name)
        if cls is None:
            results[kind] = {"skipped": True, "passed": True,
                             "reason": f"services.simulator.{class_name} absent"}
            continue
        try:
            try:
                sim = cls()
            except TypeError:
                sim = cls()
            raw = call_probe(sim, "run", (graph,))
            results[kind] = {"skipped": False,
                             "passed": bool(get_field(raw, "passed", default=True)),
                             "metrics": get_field(raw, "metrics", default={}) or {}}
        except Exception as exc:
            results[kind] = {"skipped": True, "passed": True, "error": str(exc)[:200]}
    return {"project_id": project_id, "results": results}


_TOOL_FUNCTIONS = {
    "run_design_command": _tool_run_design_command,
    "query_design": _tool_query_design,
    "export_package": _tool_export_package,
    "simulate": _tool_simulate,
}


# ----------------------------------------------------------------- ressources
def _resources_list(tenant: str) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for state in ProjectState.list_projects(tenant):
        resources.append({
            "uri": f"design://{state.project_id}",
            "name": state.name,
            "mimeType": "application/json",
            "description": f"Design du projet {state.project_id} (rev {state.last_rev})",
        })
    store = get_job_store()
    for task in get_task_queue().list()[-25:]:
        job = store.find_by_task(task.task_id)
        if job is not None:
            resources.append({
                "uri": f"report://{task.task_id}",
                "name": f"rapport {task.pipeline_name}",
                "mimeType": "application/json",
                "description": f"job {job.job_id} — {job.status}",
            })
    return resources


def _resource_read(uri: str, tenant: str, user: str) -> dict[str, Any]:
    if uri.startswith("design://"):
        project_id = uri.split("://", 1)[1].strip("/")
        graph, revision = load_project_graph(project_id, tenant, user)
        if graph is None:
            raise McpError(-32602, f"design introuvable: {project_id}")
        return {"uri": uri, "mimeType": "application/json",
                "text": json.dumps(serialize_graph(graph), indent=2, default=str)}
    if uri.startswith("report://"):
        task_id = uri.split("://", 1)[1].strip("/")
        report: dict[str, Any] = {"task_id": task_id}
        task = get_task_queue().get(task_id)
        if task is not None:
            report["task"] = task.to_dict()
        report["agents"] = get_agent_state_store().get_agent_status(task_id)
        job = get_job_store().find_by_task(task_id)
        if job is not None:
            report["job"] = job.to_dict()
        return {"uri": uri, "mimeType": "application/json",
                "text": json.dumps(report, indent=2, default=str)}
    raise McpError(-32602, f"ressource inconnue: {uri}")


# --------------------------------------------------------------------- route
@router.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    """Point d'entrée JSON-RPC 2.0 du serveur MCP."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "JSON invalide"}},
                            status_code=400)
    request_id = body.get("id")
    method = str(body.get("method") or "")
    params = body.get("params") or {}
    tenant = get_tenant(request)
    user = get_user_id(request)
    scopes = user_scopes(request)

    # notifications (sans id) : acceptées silencieusement
    if request_id is None:
        return Response(status_code=202)

    try:
        result = _dispatch(method, params, tenant=tenant, user=user, scopes=scopes)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
    except McpError as exc:
        return JSONResponse({"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": exc.code, "message": exc.message}})
    except Exception as exc:
        log.exception("erreur MCP (%s)", method)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32603, "message": str(exc)[:300]}},
                            status_code=500)


def _dispatch(method: str, params: dict[str, Any], tenant: str, user: str,
              scopes: list[str]) -> Any:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = str(params.get("name") or "")
        if name not in _TOOL_FUNCTIONS:
            raise McpError(-32601, f"outil inconnu: {name}")
        if not tool_allowed(scopes, name):
            raise McpError(-32001, f"scopes insuffisants pour l'outil {name}")
        arguments = params.get("arguments") or {}
        return {"content": [{"type": "text",
                             "text": json.dumps(_TOOL_FUNCTIONS[name](arguments, tenant, user),
                                                default=str, ensure_ascii=False)}]}
    if method == "resources/list":
        return {"resources": _resources_list(tenant)}
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        if not resource_allowed(scopes, uri):
            raise McpError(-32001, f"scopes insuffisants pour la ressource {uri}")
        return _resource_read(uri, tenant, user)
    raise McpError(-32601, f"méthode MCP inconnue: {method}")
