"""Utilitaires d'intégration transverses aux services (publication d'événements).

Placé hors des packages métier pour éviter toute collision avec design_core.
"""
from __future__ import annotations

import asyncio

from shared.events import Event, get_event_bus
from shared.utilities import get_logger

log = get_logger(__name__)


def publish_event_now(event: Event) -> bool:
    """Publie un event en fire-and-forget (sync ou async, ne lève jamais).

    Retourne True si la publication a été programmée/effectuée.
    """
    bus = get_event_bus()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if loop is not None:
            loop.create_task(bus.publish(event))
            return True
        asyncio.run(bus.publish(event))
        return True
    except Exception as exc:  # un event ne doit jamais casser le métier
        log.warning("publication event %s impossible: %s", event.type, exc)
        return False


def make_and_publish(event_type: str, payload: dict, *, project_id: str = "",
                     source: str = "") -> bool:
    """Raccourci : make_event + publish_event_now."""
    from shared.events import make_event

    evt = make_event(event_type, payload, project_id=project_id, source=source)
    return publish_event_now(evt)


def event_or_none() -> Event | None:  # pragma: no cover — utilitaire de type
    return None
