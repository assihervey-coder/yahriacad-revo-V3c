"""Jobs de workflow — suivi d'exécution + persistance JSON.

Chemin : data/projects/{tenant}/{project}/jobs/{job_id}.json
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.utilities import get_logger, new_id

from orchestrator.common import data_root

log = get_logger("workflow.jobs")


@dataclass
class Job:
    """Exécution d'une TaskSpec : étape courante, état, journal d'événements."""

    job_id: str = field(default_factory=lambda: new_id("job"))
    task_id: str = ""
    current_step: str = ""
    status: str = "queued"           # queued|running|completed|failed|escalated
    state: dict[str, Any] = field(default_factory=dict)
    events_log: list[dict[str, Any]] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)
    updated_ts: float = field(default_factory=time.time)

    def to_dict(self, include_events: bool = True) -> dict[str, Any]:
        payload = {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "current_step": self.current_step,
            "status": self.status,
            "state": {k: v for k, v in self.state.items() if k != "graph_dict"},
            "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
        }
        if include_events:
            payload["events_log"] = self.events_log
        return payload


class JobStore:
    """Registre mémoire + persistance JSON par job."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base = Path(base_dir) if base_dir else data_root()
        self._jobs: dict[str, Job] = {}
        self._by_task: dict[str, str] = {}
        self._by_correlation: dict[str, list[str]] = {}

    # -- cycle de vie ---------------------------------------------------------
    def create(self, task: Any) -> Job:
        """Crée un job lié à une TaskSpec (détecte task_id/correlation_id)."""
        job = Job(task_id=getattr(task, "task_id", "") or "")
        job.state = {
            "project_id": getattr(task, "project_id", "") or "sans-projet",
            "tenant_id": getattr(task, "tenant_id", "default") or "default",
            "correlation_id": getattr(task, "correlation_id", "") or "",
            "pipeline": getattr(task, "pipeline_name", "") or "",
        }
        self._jobs[job.job_id] = job
        if job.task_id:
            self._by_task[job.task_id] = job.job_id
        correlation = job.state.get("correlation_id")
        if correlation:
            self._by_correlation.setdefault(str(correlation), []).append(job.job_id)
        self.update(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def find_by_task(self, task_id: str) -> Job | None:
        job_id = self._by_task.get(task_id)
        return self._jobs.get(job_id) if job_id else None

    def find_by_correlation(self, correlation_id: str) -> list[Job]:
        return [self._jobs[jid] for jid in self._by_correlation.get(correlation_id, [])
                if jid in self._jobs]

    def update(self, job: Job) -> Job:
        job.updated_ts = time.time()
        self._jobs[job.job_id] = job
        self._persist(job)
        return job

    def log_event(self, job: Job, event_type: str, payload: dict[str, Any]) -> None:
        """Ajoute un événement au journal du job (et persiste)."""
        entry = {"ts": round(time.time(), 3), "type": event_type, **payload}
        job.events_log.append(entry)
        self.update(job)

    # -- persistance ----------------------------------------------------------
    def _job_dir(self, job: Job) -> Path:
        tenant = str(job.state.get("tenant_id") or "default")
        project = str(job.state.get("project_id") or "sans-projet")
        return self.base / tenant / project / "jobs"

    def _persist(self, job: Job) -> None:
        try:
            directory = self._job_dir(job)
            directory.mkdir(parents=True, exist_ok=True)
            tmp = directory / f"{job.job_id}.tmp"
            tmp.write_text(json.dumps(job.to_dict(), indent=2, default=str), encoding="utf-8")
            os.replace(tmp, directory / f"{job.job_id}.json")
        except Exception:
            log.debug("persistance job %s impossible", job.job_id, exc_info=True)


_STORE: JobStore | None = None


def get_job_store() -> JobStore:
    """Singleton partagé (API + runner + MCP)."""
    global _STORE
    if _STORE is None:
        _STORE = JobStore()
    return _STORE
