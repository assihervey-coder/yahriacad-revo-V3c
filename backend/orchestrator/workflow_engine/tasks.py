"""Tâches de workflow — TaskSpec + file d'attente asynchrone en mémoire."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestrator.common import get_main_loop
from shared.utilities import get_logger, new_id

log = get_logger("workflow.tasks")


@dataclass
class TaskSpec:
    """Unité de travail : un pipeline à exécuter sur un projet."""

    task_id: str = field(default_factory=lambda: new_id("task"))
    pipeline_name: str = "full_design"
    params: Dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    tenant_id: str = "default"
    status: str = "pending"          # pending|running|completed|failed|escalated
    created_ts: float = field(default_factory=time.time)
    result: Optional[Dict[str, Any]] = None
    correlation_id: str = ""
    priority: int = 5                # 1 (haute) → 9 (basse)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "pipeline_name": self.pipeline_name,
            "params": {k: v for k, v in self.params.items()
                       if k not in ("graph", "graph_dict")},
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "created_ts": self.created_ts,
            "result": self.result,
            "correlation_id": self.correlation_id,
            "priority": self.priority,
        }


class TaskQueue:
    """File asyncio + registre des tâches (in-memory, mono-processus).

    `submit` est thread-safe : si appelé hors de la boucle principale, la mise
    en file est relayée via `call_soon_threadsafe`.
    """

    def __init__(self) -> None:
        self._queue: "asyncio.Queue[TaskSpec]" = asyncio.Queue()
        self._tasks: Dict[str, TaskSpec] = {}
        self._order: List[str] = []

    # -- opérations ---------------------------------------------------------
    def submit(self, task: TaskSpec) -> TaskSpec:
        """Enfile une tâche (idempotent sur le task_id)."""
        if task.task_id in self._tasks:
            return task
        self._tasks[task.task_id] = task
        self._order.append(task.task_id)
        loop = _running_loop()
        main = get_main_loop()
        if loop is main or main is None or not main.is_running():
            self._queue.put_nowait(task)
        else:
            main.call_soon_threadsafe(self._queue.put_nowait, task)
        log.info("tâche soumise: %s (%s, projet %s)", task.task_id, task.pipeline_name, task.project_id)
        return task

    async def dequeue(self) -> TaskSpec:
        """Retire et retourne la prochaine tâche (await)."""
        task = await self._queue.get()
        return task

    def get(self, task_id: str) -> Optional[TaskSpec]:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: str,
                      result: Optional[Dict[str, Any]] = None) -> Optional[TaskSpec]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = status
        if result is not None:
            task.result = result
        return task

    def list(self) -> List[TaskSpec]:
        """Toutes les tâches connues, par ordre de soumission."""
        return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def pending_count(self) -> int:
        return self._queue.qsize()


def _running_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


_QUEUE: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Singleton partagé (API + runner + MCP)."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = TaskQueue()
    return _QUEUE
