"""Helpers d'émission d'événements depuis du code synchrone.

Le bus est asynchrone (`await bus.publish`) ; les modules synchrones
(verifier, rollback, optimizer) utilisent `publish_nowait` qui :
- schedule la publication sur la boucle courante si elle tourne ;
- sinon exécute la publication dans une boucle éphémère (fire-and-forget).
"""
from __future__ import annotations

import asyncio
from typing import Any

from shared.events import Event, get_event_bus
from shared.utilities import get_logger

log = get_logger("ai_engine.events")


def publish_nowait(event: Event) -> None:
    """Publie un event depuis du code synchrone sans bloquer ni casser."""
    bus = get_event_bus()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(bus.publish(event))
        return
    try:
        asyncio.run(bus.publish(event))
    except Exception as exc:  # un bus défaillant ne casse jamais l'appelant
        log.debug("publication event %s impossible: %s", event.type, exc)


def emit(event_type: str, payload: dict | None = None, **kwargs: Any) -> None:
    """Fabrique + publie un event (helper one-liner)."""
    from shared.events import make_event

    publish_nowait(make_event(event_type, payload=payload or {}, **kwargs))
