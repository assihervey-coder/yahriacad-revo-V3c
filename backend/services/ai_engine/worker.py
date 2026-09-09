"""Worker AI Engine — consomme l'event bus et exécute les tâches agents.

Topics écoutés : AGENT_TASK_ASSIGNED (payload.role ∈ {researcher, selector,
corrector}). Boucle asyncio startable / stoppable ; actions minimales réelles :
- researcher  : RAG answer sur la question du payload ;
- selector    : IntentParser sur le texte puis hints composants ;
- corrector   : SelfVerifier + rollback via DesignVersioning si fourni.
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

from shared.events import Event, EventTypes, get_event_bus, make_event
from shared.utilities import get_logger, new_id

from services.ai_engine.llm_orchestrator.intent_parser import IntentParser
from services.ai_engine.rag_engine.rag_engine import RAGEngine
from services.ai_engine.self_verifier.verifier import SelfVerifier

log = get_logger("ai_engine.worker")

HANDLED_ROLES = {"researcher", "selector", "corrector"}


class AIEngineWorker:
    """Worker asyncio du AI Engine — traite les tâches assignées par rôle."""

    def __init__(self,
                 rag: RAGEngine | None = None,
                 parser: IntentParser | None = None,
                 verifier: SelfVerifier | None = None,
                 versioning=None) -> None:  # noqa: ANN001
        self.rag = rag
        self.parser = parser or IntentParser()
        self.verifier = verifier or SelfVerifier(versioning=versioning)
        self.versioning = versioning
        self._running = False
        self._tasks_processed = 0
        self.bus = get_event_bus()

    # ------------------------------------------------------------ handlers
    async def handle_event(self, event: Event) -> None:
        """Point d'entrée du bus — dispatch par rôle."""
        payload = event.payload or {}
        role = str(payload.get("role", "")).lower()
        if role not in HANDLED_ROLES:
            return
        log.info("tâche reçue: role=%s correlation=%s",
                 role, event.correlation_id or "-")
        try:
            if role == "researcher":
                result = self._do_research(payload)
            elif role == "selector":
                result = self._do_select(payload)
            else:
                result = self._do_correct(payload)
        except Exception as exc:
            log.exception("tâche %s échouée", role)
            result = {"ok": False, "error": str(exc)}

        self._tasks_processed += 1
        await self.bus.publish(make_event(
            EventTypes.AGENT_TASK_COMPLETED,
            payload={"role": role, "result": result,
                     "task_id": payload.get("task_id", new_id("task"))},
            project_id=event.project_id,
            correlation_id=event.correlation_id,
            source="ai_engine.worker",
        ))

    # -------------------------------------------------------------- actions
    def _do_research(self, payload: dict[str, Any]) -> dict[str, Any]:
        """researcher : réponse RAG à la question du payload."""
        question = str(payload.get("question")
                       or payload.get("text")
                       or payload.get("objective", ""))
        if not question:
            return {"ok": False, "error": "aucune question fournie"}
        if self.rag is None:
            return {"ok": True, "answer":
                    "RAG non configuré — question notée pour enrichissement.",
                    "question": question}
        ans = self.rag.answer(question)
        return {"ok": True, "question": question, "answer": ans.text,
                "sources": ans.sources, "confidence": ans.confidence}

    def _do_select(self, payload: dict[str, Any]) -> dict[str, Any]:
        """selector : parse l'intention et retourne les hints composants."""
        text = str(payload.get("text")
                   or payload.get("objective")
                   or payload.get("requirement", ""))
        if not text:
            return {"ok": False, "error": "aucun texte fourni"}
        parsed = self.parser.parse(text)
        return {"ok": True, "project_type": parsed.project_type,
                "layers": parsed.layers,
                "component_hints": parsed.component_hints,
                "target_factory": parsed.target_factory,
                "confidence": parsed.confidence}

    def _do_correct(self, payload: dict[str, Any]) -> dict[str, Any]:
        """corrector : vérifie le graphe (dict) et propose des correctifs."""
        graph = payload.get("graph")
        if graph is None:
            return {"ok": False, "error": "aucun graphe fourni"}
        report = self.verifier.verify(graph, context=payload.get("context"))
        return {"ok": True, "passed": report.passed,
                "confidence": report.confidence,
                "issues": report.issues[:20],
                "rollback_needed": not report.passed}

    # ----------------------------------------------------------- lifecycle
    async def start(self, poll_interval: float = 0.5) -> None:
        """Boucle asyncio : s'abonne au bus et tourne jusqu'à stop()."""
        if self._running:
            return
        self._running = True
        self.bus.subscribe(EventTypes.AGENT_TASK_ASSIGNED, self.handle_event)
        log.info("worker AI Engine démarré (roles=%s)", sorted(HANDLED_ROLES))
        try:
            while self._running:
                await asyncio.sleep(poll_interval)
        finally:
            self.bus.unsubscribe(EventTypes.AGENT_TASK_ASSIGNED, self.handle_event)
            log.info("worker AI Engine arrêté (%d tâches traitées)",
                     self._tasks_processed)

    def stop(self) -> None:
        """Demande l'arrêt de la boucle."""
        self._running = False

    @property
    def tasks_processed(self) -> int:
        return self._tasks_processed


async def main_forever() -> None:
    """Boucle principale (docker/CLI) : gère SIGINT/SIGTERM proprement."""
    worker = AIEngineWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, worker.stop)
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main_forever())
