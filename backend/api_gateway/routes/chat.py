"""Route chat — commandes en langage naturel → pipeline full_design en tâche de fond.

POST /api/v1/chat/commands      → ChatCommandResponse (acceptation immédiate)
GET  /api/v1/chat/commands/{cid}/status → état du job lié
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from shared.events import make_event
from shared.schemas import ChatCommandRequest, ChatCommandResponse
from shared.utilities import get_logger, new_id

from api_gateway.deps import get_tenant, get_user_id
from orchestrator.common import get_field, publish_event, try_import
from orchestrator.state_manager import ProjectState
from orchestrator.workflow_engine.jobs import get_job_store
from orchestrator.workflow_engine.pipelines import PIPELINES
from orchestrator.workflow_engine.tasks import TaskSpec, get_task_queue

log = get_logger("api.chat")

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _slug(message: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", message.lower()).strip("-")[:40]
    return slug or "projet-chat"


def _intent_and_plan(message: str) -> tuple[str, str]:
    """Parse l'intention + construit un résumé de plan (repli déterministe)."""
    intent, plan_summary = "generic_design", ""
    parser_cls = try_import("services.ai_engine", ["IntentParser"]).get("IntentParser")
    intents = None
    if parser_cls is not None:
        try:
            parser = parser_cls()
            parsed = parser.parse(message)
            intent = str(get_field(parsed, "project_type", default="") or "generic_design")
            intents = parser.to_intent_graph(parsed)
        except Exception as exc:
            log.debug("IntentParser indisponible: %s", exc)
    try:
        from orchestrator.super_agent.planning.planner import Planner

        plan = Planner().build_plan(intents)
        plan_summary = " → ".join(d.role.value for d in plan)
    except Exception:
        plan_summary = " → ".join(step.name for step in PIPELINES["full_design"].steps)
    return intent, plan_summary


def submit_chat_command(message: str, project_id: str = "", tenant: str = "default",
                        session_id: str = "", user_id: str = "default") -> dict[str, Any]:
    """Crée le projet si besoin, publie chat.command et soumet la tâche full_design.

    Retourne immédiatement {accepted, intent, plan_summary, job_id, ...} —
    l'exécution continue en tâche de fond dans le runner.
    """
    message = (message or "").strip()
    if not message:
        raise ValueError("message vide")
    tenant = tenant or "default"
    user_id = user_id or "default"

    if project_id:
        if ProjectState.load(project_id, tenant, user_id) is None:
            ProjectState.create(_slug(message), tenant_id=tenant, user_id=user_id,
                                project_id=project_id)
    else:
        project_id = ProjectState.create(_slug(message), tenant_id=tenant,
                                         user_id=user_id).project_id

    intent, plan_summary = _intent_and_plan(message)
    correlation_id = new_id("cmd")

    # La tâche est soumise ici (job_id immédiat) ; l'event sert de trace +
    # de mécanisme de rattrapage pour les producteurs externes (MCP, runner).
    task = TaskSpec(
        pipeline_name="full_design",
        params={"message": message, "user_id": user_id, "session_id": session_id},
        project_id=project_id,
        tenant_id=tenant,
        correlation_id=correlation_id,
    )
    get_task_queue().submit(task)
    publish_event(make_event(
        "chat.command",
        {"message": message, "project_id": project_id, "session_id": session_id,
         "user_id": user_id, "task_id": task.task_id},
        project_id=project_id, tenant_id=tenant, source="api_gateway.chat",
        correlation_id=correlation_id,
    ))
    log.info("commande chat acceptée: %s → tâche %s (projet %s)",
             correlation_id, task.task_id, project_id)
    return {
        "accepted": True,
        "intent": intent,
        "plan_summary": plan_summary,
        "job_id": task.task_id,
        "correlation_id": correlation_id,
        "project_id": project_id,
        "reply": (f"Commande acceptée — intention « {intent} ». Le pipeline full_design "
                  f"({plan_summary}) s'exécute en tâche de fond."),
    }


@router.post("/commands", response_model=ChatCommandResponse)
async def post_command(payload: ChatCommandRequest, request: Request) -> ChatCommandResponse:
    """Accepte une commande NL et lance le pipeline en arrière-plan."""
    tenant = get_tenant(request) if payload.tenant_id in ("", "default") else payload.tenant_id
    try:
        result = submit_chat_command(
            message=payload.message,
            project_id=payload.project_id,
            tenant=tenant,
            session_id=payload.session_id,
            user_id=get_user_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ChatCommandResponse(
        accepted=bool(result["accepted"]),
        intent=result["intent"],
        plan_summary=result["plan_summary"],
        job_id=result["job_id"],
        reply=result["reply"],
        agent_activity=[],
    )


@router.get("/commands/{correlation_id}/status")
async def get_command_status(correlation_id: str, request: Request) -> dict[str, Any]:
    """État d'une commande : tâche, job, étapes, derniers événements."""
    # la commande est tracée par correlation_id → tâche
    task = None
    for candidate in get_task_queue().list():
        if candidate.correlation_id == correlation_id:
            task = candidate
            break
    if task is None:
        raise HTTPException(status_code=404, detail=f"correlation_id inconnu: {correlation_id}")
    job = get_job_store().find_by_task(task.task_id)
    payload: dict[str, Any] = {
        "correlation_id": correlation_id,
        "task_id": task.task_id,
        "status": task.status,
        "project_id": task.project_id,
        "pipeline": task.pipeline_name,
    }
    if job is not None:
        payload.update({
            "job_id": job.job_id,
            "current_step": job.current_step,
            "completed_steps": job.state.get("completed_steps", []),
            "graph_stats": job.state.get("graph_stats"),
            "events": job.events_log[-10:],
        })
    return payload
