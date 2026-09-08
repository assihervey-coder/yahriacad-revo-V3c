"""Event bus — pub/sub asynchrone.

`InProcessEventBus` : défaut (tests, dev mono-processus).
`RedisEventBus`    : production (distribué entre services docker/k8s).
Obtention via `get_event_bus()` selon EVENT_BUS_BACKEND.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Protocol

from shared.events.events import Event

log = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...
    def subscribe(self, event_type: str, handler: Handler) -> None: ...
    def unsubscribe(self, event_type: str, handler: Handler) -> None: ...


class InProcessEventBus:
    """Bus en mémoire — livré avec la plateforme, zéro dépendance."""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self._history: List[Event] = []
        self._max_history = 10_000

    async def publish(self, event: Event) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            del self._history[: len(self._history) - self._max_history]
        handlers = list(self._subs.get(event.type, [])) + list(self._subs.get("*", []))
        for h in handlers:
            try:
                result = h(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # un handler défaillant ne tue jamais le bus
                log.exception("event handler error (%s)", event.type)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Handler) -> None:
        if handler in self._subs.get(event_type, []):
            self._subs[event_type].remove(handler)

    def history(self, event_type: str | None = None) -> List[Event]:
        if event_type is None:
            return list(self._history)
        return [e for e in self._history if e.type == event_type]


class RedisEventBus(InProcessEventBus):
    """Bus Redis pub/sub (production). Hérite du bus local pour l'historique.

    Le channel = type d'event ; les handlers locaux restent appelés en plus
    de la diffusion Redis (permet la mixité in-process / inter-services).
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        super().__init__()
        self._redis_url = redis_url
        self._redis = None  # lazy

    async def _client(self):
        if self._redis is None:
            import redis.asyncio as aioredis  # optional dep

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def publish(self, event: Event) -> None:
        await super().publish(event)
        try:
            client = await self._client()
            import orjson

            await client.publish(f"pcb3:{event.type}", orjson.dumps({
                "type": event.type, "payload": event.payload,
                "project_id": event.project_id, "correlation_id": event.correlation_id,
            }).decode())
        except Exception:
            log.warning("redis publish failed — event conservé localement")


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        backend = os.getenv("EVENT_BUS_BACKEND", "inprocess")
        if backend == "redis":
            _bus = RedisEventBus(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        else:
            _bus = InProcessEventBus()
    return _bus
