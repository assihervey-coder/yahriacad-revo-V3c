"""WebSocket live — flux temps réel des événements du bus par projet.

Endpoint : /ws/{project_id}
  - s'abonne au bus (topic "*"), filtre sur le projet,
  - envoie {type, payload, ts} en JSON,
  - ping/pong (le serveur ping toutes les 20s, répond "pong" aux pings client),
  - gère proprement la déconnexion (unsubscribe + fermeture).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from shared.events import get_event_bus
from shared.utilities import get_logger

log = get_logger("api.ws")

router = APIRouter(tags=["websocket"])

PING_INTERVAL_S = 20.0


@router.websocket("/ws/{project_id}")
async def live_feed(websocket: WebSocket, project_id: str) -> None:
    """Flux live des événements d'un projet (abonnement topic '*')."""
    await websocket.accept()
    bus = get_event_bus()
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=500)

    def handler(event: Any) -> None:
        # filtre : events du projet (ou globaux) uniquement
        if event.project_id and event.project_id != project_id:
            return
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)

    bus.subscribe("*", handler)
    log.info("ws connecté — projet %s", project_id)
    recv_task: asyncio.Task | None = None
    evt_task: asyncio.Task | None = None
    try:
        await websocket.send_json({"type": "connected",
                                   "payload": {"project_id": project_id},
                                   "ts": time.time()})
        recv_task = asyncio.create_task(websocket.receive_text())
        while True:
            if evt_task is None:
                evt_task = asyncio.create_task(queue.get())
            done, _pending = await asyncio.wait({recv_task, evt_task},
                                                timeout=PING_INTERVAL_S,
                                                return_when=asyncio.FIRST_COMPLETED)
            if evt_task in done:
                event = evt_task.result()
                evt_task = None
                await websocket.send_json({"type": event.type,
                                           "payload": event.payload,
                                           "ts": event.ts})
            if recv_task in done:
                message = recv_task.result()
                recv_task = asyncio.create_task(websocket.receive_text())
                if str(message).strip().lower() == "ping":
                    await websocket.send_json({"type": "pong", "payload": {},
                                               "ts": time.time()})
            if not done:  # timeout → keepalive
                await websocket.send_json({"type": "ping", "payload": {},
                                           "ts": time.time()})
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    except Exception:
        log.debug("ws erreur inattendue", exc_info=True)
    finally:
        bus.unsubscribe("*", handler)
        for task in (recv_task, evt_task):
            if task is not None and not task.done():
                task.cancel()
        with contextlib.suppress(Exception):
            await websocket.close()
        log.info("ws déconnecté — projet %s", project_id)
