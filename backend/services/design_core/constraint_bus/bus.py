"""ConstraintBus — pub/sub de contraintes avec pont vers l'event bus partagé.

Sujets internes : "constraint.updated", "constraint.violated",
"constraint.revalidated". Chaque publication est journalisée dans un
historique interne ET publiée sur `shared.events` (EventTypes.CONSTRAINT_*).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from shared.events.event_bus import get_event_bus
from shared.events.events import EventTypes, make_event

log = logging.getLogger(__name__)

# Sujets du bus de contraintes
TOPIC_UPDATED = "constraint.updated"
TOPIC_VIOLATED = "constraint.violated"
TOPIC_REVALIDATED = "constraint.revalidated"

# Correspondance sujet -> type d'event partagé
_TOPIC_TO_EVENT: Dict[str, str] = {
    TOPIC_UPDATED: EventTypes.CONSTRAINT_UPDATED,
    TOPIC_VIOLATED: EventTypes.CONSTRAINT_VIOLATED,
    TOPIC_REVALIDATED: EventTypes.CONSTRAINT_UPDATED,
}

Callback = Callable[[Dict[str, Any]], Any]

# --- dispatch async non bloquant (loop courante si async, sinon loop de fond) ---
_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_lock = threading.Lock()


def _ensure_bg_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop
    with _bg_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            threading.Thread(
                target=_bg_loop.run_forever, daemon=True, name="constraint-bus-loop",
            ).start()
        return _bg_loop


def _fire_and_forget(coro: Any) -> None:
    """Exécute une coroutine sans bloquer l'appelant (sync ou async)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(coro)
    else:
        asyncio.run_coroutine_threadsafe(coro, _ensure_bg_loop())


class ConstraintBus:
    """Bus de diffusion des mises à jour et violations de contraintes."""

    TOPIC_UPDATED = TOPIC_UPDATED
    TOPIC_VIOLATED = TOPIC_VIOLATED
    TOPIC_REVALIDATED = TOPIC_REVALIDATED

    def __init__(self, project_id: str = "", max_history: int = 5_000) -> None:
        self.project_id = project_id
        self._subs: Dict[str, List[Callback]] = defaultdict(list)
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history

    # ------------------------------------------------------------------ pub/sub
    def subscribe(self, topic: str, callback: Callback) -> None:
        """Abonne un callback (sync ou async) à un sujet."""
        self._subs[topic].append(callback)

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publie sur le bus interne (+ historique) ET sur l'event bus shared."""
        entry = {"topic": topic, "payload": dict(payload), "ts": time.time(),
                 "project_id": self.project_id}
        self._history.append(entry)
        if len(self._history) > self._max_history:
            del self._history[: len(self._history) - self._max_history]

        for callback in list(self._subs.get(topic, [])):
            try:
                result = callback(entry["payload"])
                if asyncio.iscoroutine(result):
                    _fire_and_forget(result)
            except Exception:
                log.exception("callback constraint bus défaillant (%s)", topic)

        event_type = _TOPIC_TO_EVENT.get(topic)
        if event_type:
            try:
                _fire_and_forget(get_event_bus().publish(make_event(
                    event_type, payload=entry["payload"],
                    project_id=self.project_id, source="design_core.constraint_bus",
                )))
            except Exception:
                log.exception("publication event bus impossible (%s)", topic)

    # ------------------------------------------------------------------ helpers
    def broadcast_update(self, constraint_id: str, new_spec: Dict[str, Any]) -> None:
        """Diffuse une mise à jour de spécification de contrainte (reconfiguration)."""
        self.publish(TOPIC_UPDATED, {
            "constraint_id": constraint_id, "spec": dict(new_spec), "action": "update",
        })

    def publish_violations(self, report: Any) -> None:
        """Publie chaque violation d'un ConstraintReport sur le sujet 'violated'."""
        for violation in getattr(report, "violations", []):
            self.publish(TOPIC_VIOLATED, {
                "constraint_id": violation.constraint_id,
                "severity": violation.severity,
                "category": violation.category,
                "message": violation.message,
                "location": violation.location,
            })

    def publish_revalidated(self, constraint_ids: List[str], reason: str = "") -> None:
        """Signale qu'un lot de contraintes a été re-vérifié (ex: après édition)."""
        self.publish(TOPIC_REVALIDATED, {"constraint_ids": list(constraint_ids), "reason": reason})

    def violation_history(self, constraint_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Historique interne des publications (filtrable par contrainte)."""
        if constraint_id is None:
            return [dict(e) for e in self._history]
        return [
            dict(e) for e in self._history
            if e["payload"].get("constraint_id") == constraint_id
        ]


# --- singleton plateforme ----------------------------------------------------
_bus: Optional[ConstraintBus] = None


def get_constraint_bus(project_id: str = "") -> ConstraintBus:
    """Singleton du bus de contraintes (un par process)."""
    global _bus
    if _bus is None:
        _bus = ConstraintBus(project_id=project_id)
    elif project_id and not _bus.project_id:
        _bus.project_id = project_id
    return _bus


def reset_constraint_bus() -> None:
    """Réinitialise le singleton (tests)."""
    global _bus
    _bus = None
