"""Hôte KiCad live — pont WebSocket vers l'API IPC de KiCad (pcbnew).

Implémentation réelle avec `websockets`, fallback gracieux en mode offline
(log warning) si le serveur KiCad n'est pas joignable.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from shared.utilities import get_logger

from services.pcb_plugin._compat import graph_from_dict, graph_to_dict

log = get_logger(__name__)

DesignChangeCallback = Callable[[dict], None | Awaitable[None]]


class KiCadLiveHost:
    """Client WebSocket asynchrone pour un KiCad à l'écoute (port 7999 par défaut)."""

    def __init__(self, ws_url: str = "ws://localhost:7999", open_timeout: float = 3.0) -> None:
        self.ws_url = ws_url
        self.open_timeout = open_timeout
        self._ws: Any = None
        self._connected = False
        self._listener: asyncio.Task | None = None
        self._on_change: DesignChangeCallback | None = None

    # -- cycle de vie -------------------------------------------------------
    @property
    def connected(self) -> bool:
        """True si le socket KiCad est ouvert."""
        return self._connected

    async def connect(self) -> bool:
        """Ouvre la connexion ; retourne False + warning en cas d'échec (mode offline)."""
        try:
            import websockets  # dépendance déclarée dans pyproject

            self._ws = await asyncio.wait_for(
                websockets.connect(self.ws_url), timeout=self.open_timeout
            )
            self._connected = True
            log.info("KiCad live host connecté (%s)", self.ws_url)
            if self._on_change is not None:
                self._start_listener()
        except Exception as exc:
            self._connected = False
            self._ws = None
            log.warning("KiCad live host injoignable (%s) — mode offline", exc)
        return self._connected

    async def disconnect(self) -> None:
        """Ferme le socket et le listener."""
        if self._listener is not None:
            self._listener.cancel()
            self._listener = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None
        self._connected = False
        log.info("KiCad live host déconnecté")

    # -- événements entrants --------------------------------------------------
    def on_design_change(self, callback: DesignChangeCallback) -> None:
        """Enregistre le callback des events KiCad push (dict JSON)."""
        self._on_change = callback
        if self._connected and self._ws is not None and self._listener is None:
            self._start_listener()

    def _start_listener(self) -> None:
        self._listener = asyncio.create_task(self._listen(), name="kicad-live-listener")

    async def _listen(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    log.warning("message KiCad non-JSON ignoré")
                    continue
                if self._on_change is not None:
                    result = self._on_change(data)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._connected = False
            log.warning("listener KiCad interrompu (%s) — mode offline", exc)

    # -- échanges design ------------------------------------------------------
    async def push_design(self, graph: Any) -> bool:
        """Pousse le graphe sérialisé vers KiCad. False si offline."""
        if not self._connected or self._ws is None:
            log.warning("push_design ignoré — KiCad offline")
            return False
        payload = json.dumps({
            "type": "design.update",
            "project_id": getattr(graph, "project_id", ""),
            "graph": graph_to_dict(graph),
        }, default=str)
        try:
            await self._ws.send(payload)
            return True
        except Exception as exc:
            self._connected = False
            log.warning("push_design échoué (%s) — mode offline", exc)
            return False

    async def pull_design(self) -> Any | None:
        """Demande et récupère le design KiCad courant (None si offline/échec)."""
        if not self._connected or self._ws is None:
            log.warning("pull_design ignoré — KiCad offline")
            return None
        try:
            await self._ws.send(json.dumps({"type": "design.pull"}))
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self.open_timeout)
            data = json.loads(raw)
            graph_data = data.get("graph", data) if isinstance(data, dict) else {}
            return graph_from_dict(graph_data)
        except Exception as exc:
            log.warning("pull_design échoué (%s)", exc)
            return None
