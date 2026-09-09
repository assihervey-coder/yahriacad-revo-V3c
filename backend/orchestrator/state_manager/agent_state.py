"""État des agents par tâche — data/projects/agent_state.json.

Utilisé par le workflow engine (suivi live) et l'API/GraphQL (who is doing what).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from shared.utilities import get_logger

from orchestrator.common import data_root

log = get_logger("state.agents")


class AgentStateStore:
    """Registre (task_id, rôle) → statut/confiance, persisté en JSON."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else data_root() / "agent_state.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    # -- persistance ----------------------------------------------------------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("agent_state.json illisible — départ à vide", exc_info=True)
            self._data = {}

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            log.debug("persistance agent_state impossible", exc_info=True)

    # -- opérations --------------------------------------------------------------
    def set_agent_status(self, task_id: str, role: str, status: str,
                         confidence: float = 0.0,
                         output: dict[str, Any] | None = None) -> None:
        """Met à jour le statut d'un agent pour une tâche."""
        entry = {
            "role": str(role),
            "status": str(status),
            "confidence": round(float(confidence or 0.0), 4),
            "ts": time.time(),
            "output": output or {},
        }
        with self._lock:
            self._data.setdefault(str(task_id), {})[str(role)] = entry
            self._persist()

    def get_agent_status(self, task_id: str) -> dict[str, dict[str, Any]]:
        """Statut de tous les agents d'une tâche : {role: entry}."""
        with self._lock:
            snapshot = self._data.get(str(task_id), {})
            return json.loads(json.dumps(snapshot, default=str))

    def active_agents(self) -> list[dict[str, Any]]:
        """Agents actuellement en cours d'exécution (status == running)."""
        active: list[dict[str, Any]] = []
        with self._lock:
            for task_id, roles in self._data.items():
                for _role, entry in roles.items():
                    if entry.get("status") == "running":
                        active.append({"task_id": task_id, **entry})
        return active

    def tasks(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())


_STORE: AgentStateStore | None = None


def get_agent_state_store() -> AgentStateStore:
    """Singleton partagé (API + workflow engine)."""
    global _STORE
    if _STORE is None:
        _STORE = AgentStateStore()
    return _STORE
