"""Runner du workflow — boucle asyncio consommant la TaskQueue.

Source de tâches :
  - file asyncio (API REST, MCP, optimisation...),
  - topic "chat.command" sur l'event bus (commandes en langage naturel).

Lancement autonome :  python -m orchestrator.workflow_engine.runner
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from orchestrator.common import register_main_loop
from orchestrator.workflow_engine.engine import WorkflowEngine
from orchestrator.workflow_engine.tasks import TaskSpec, get_task_queue
from shared.events import get_event_bus
from shared.utilities import configure_logging, get_logger

log = get_logger("workflow.runner")

_subscribed = False


def handle_chat_command(event: Any) -> None:
    """Handler bus : topic "chat.command" → TaskSpec full_design.

    Si l'API a déjà soumis la tâche (payload.task_id présent), on ignore
    (l'event sert alors uniquement de trace de corrélation).
    """
    payload: Dict[str, Any] = dict(event.payload or {})
    message = str(payload.get("message") or "").strip()
    if not message:
        return
    if payload.get("task_id"):
        log.debug("chat.command %s déjà soumis (tâche %s)", event.correlation_id, payload["task_id"])
        return
    task = TaskSpec(
        pipeline_name="full_design",
        params={
            "message": message,
            "user_id": str(payload.get("user_id") or "default"),
            "session_id": str(payload.get("session_id") or ""),
        },
        project_id=str(payload.get("project_id") or ""),
        tenant_id=str(event.tenant_id or "default"),
        correlation_id=str(event.correlation_id or ""),
    )
    get_task_queue().submit(task)
    log.info("chat.command → tâche %s (projet %s)", task.task_id, task.project_id)


def ensure_chat_subscription(bus: Any = None) -> None:
    """Abonne (une seule fois) le runner au topic chat.command."""
    global _subscribed
    if _subscribed:
        return
    (bus or get_event_bus()).subscribe("chat.command", handle_chat_command)
    _subscribed = True


async def consume_forever(engine: WorkflowEngine) -> None:
    """Boucle principale : déqueue une TaskSpec → run_pipeline dans un thread."""
    while True:
        try:
            task = await engine.queue.dequeue()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("dequeue impossible — nouvelle tentative dans 0.5s")
            await asyncio.sleep(0.5)
            continue
        engine.queue.update_status(task.task_id, "running")
        try:
            await asyncio.to_thread(engine.run_pipeline, task)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pipeline de la tâche %s a échoué", task.task_id)
            engine.queue.update_status(task.task_id, "failed")


async def main() -> None:
    """Point d'entrée autonome du runner (bus + file + moteur)."""
    configure_logging()
    register_main_loop(asyncio.get_running_loop())
    engine = WorkflowEngine()
    ensure_chat_subscription()
    consumer = asyncio.create_task(consume_forever(engine), name="workflow-consumer")
    log.info("runner workflow actif — %d agents, en attente de tâches…", len(engine.agents))
    try:
        await consumer
    except asyncio.CancelledError:
        log.info("runner workflow arrêté")


if __name__ == "__main__":
    asyncio.run(main())
