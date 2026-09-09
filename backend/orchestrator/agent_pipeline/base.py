"""Classe de base des 10 agents du pipeline V3.

Contrat d'exécution (imposé par le workflow engine) :
  - `execute(context)` lit le DesignGraph dans context["graph"], opère,
    retourne un AgentResultSchema (output + confidence),
  - COMMITE une révision via context["versioning"] (DesignVersioning),
  - écrit dans context["smm"] (SharedMentalModel),
  - `verify(result, context)` dit si le résultat est acceptable,
  - `rollback(context, to_rev)` restaure une révision précédente.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from shared.contracts import AgentRole
from shared.events import make_event
from shared.schemas import AgentResultSchema
from shared.schemas.agent_schemas import AgentStatus
from shared.utilities import get_logger

from orchestrator.common import (
    call_probe,
    ensure_smm,
    extract_rev,
    publish_event,
)


class BaseAgent(ABC):
    """Agent spécialisé du pipeline — une responsabilité, un rôle contractuel."""

    role: AgentRole
    description: str = ""

    def __init__(self, role: AgentRole, name: str = "", orchestrator: Any = None) -> None:
        self.role = role
        self.name = name or role.value
        self.orchestrator = orchestrator
        self.log = get_logger(f"agent.{self.name}")

    # ------------------------------------------------------------------ API
    def plan(self, objective: str, context: dict[str, Any]) -> list[str]:
        """Étapes internes que l'agent prévoit pour l'objectif donné."""
        return [objective]

    @abstractmethod
    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        """Exécute l'action de l'agent sur le graphe du contexte."""

    def verify(self, result: AgentResultSchema, context: dict[str, Any]) -> bool:
        """Auto-contrôle : le résultat est-il acceptable ?"""
        return result.status == AgentStatus.SUCCEEDED

    def rollback(self, context: dict[str, Any], to_rev: int | None) -> bool:
        """Restaure le graphe d'une révision précédente (via DesignVersioning)."""
        versioning = context.get("versioning")
        if versioning is None or to_rev is None:
            return False
        try:
            graph = versioning.restore(int(to_rev))
            if graph is not None:
                context["graph"] = graph
                return True
        except Exception:
            self.log.debug("rollback vers rev %s impossible", to_rev, exc_info=True)
        return False

    def supports(self, action: str) -> bool:
        """Capabilité : l'agent sait-il traiter cette action/objectif ?"""
        return True

    # -------------------------------------------------------------- helpers
    def emit(self, event_type: str, payload: dict[str, Any],
             context: dict[str, Any] | None = None,
             correlation_id: str = "") -> None:
        """Publie un event sur le bus (thread-safe)."""
        context = context or {}
        event = make_event(
            event_type, payload,
            project_id=str(context.get("project_id") or ""),
            tenant_id=str(context.get("tenant_id") or "default"),
            source=f"agent.{self.name}",
            correlation_id=str(context.get("correlation_id") or correlation_id or ""),
        )
        publish_event(event)

    def make_result(self, context: dict[str, Any],
                    status: AgentStatus,
                    output: dict[str, Any],
                    confidence: float,
                    rationale: str = "",
                    revision_created: int | None = None,
                    rollback_to: int | None = None) -> AgentResultSchema:
        """Construit un AgentResultSchema normalisé (confidence bornée 0..1)."""
        return AgentResultSchema(
            task_id=str(context.get("task_id") or ""),
            role=self.role.value,
            status=status,
            output=output,
            confidence=float(max(0.0, min(1.0, confidence))),
            rationale=rationale,
            revision_created=revision_created,
            rollback_to=rollback_to,
        )

    def succeeded(self, context: dict[str, Any], output: dict[str, Any],
                  confidence: float, rationale: str = "") -> AgentResultSchema:
        return self.make_result(context, AgentStatus.SUCCEEDED, output, confidence, rationale)

    def failed(self, context: dict[str, Any], rationale: str,
               output: dict[str, Any] | None = None) -> AgentResultSchema:
        return self.make_result(context, AgentStatus.FAILED, output or {}, 0.0, rationale)

    def commit(self, context: dict[str, Any], message: str) -> int | None:
        """Commit une révision du graphe courant via DesignVersioning."""
        graph = context.get("graph")
        versioning = context.get("versioning")
        if graph is None or versioning is None:
            return None
        try:
            revision = versioning.commit(graph, message, author=f"agent:{self.role.value}")
            rev = extract_rev(revision)
            if rev is not None:
                context["revision"] = rev
            return rev
        except Exception as exc:
            self.log.warning("commit impossible: %s", exc)
            return None

    def record_decision(self, context: dict[str, Any], subject: str, detail: Any,
                        confidence: float = 0.8) -> None:
        """Trace une décision dans le SharedMentalModel (tolérant aux signatures)."""
        ensure_smm(context)
        call_probe(
            context.get("smm"), "record_decision",
            (subject, detail, float(confidence)),
            (subject, str(detail)),
            (str(detail),),
        )

    def record_tradeoff(self, context: dict[str, Any], topic: str,
                        chosen: Any, rejected: Any, reason: str = "") -> None:
        """Trace un arbitrage dans le SharedMentalModel."""
        call_probe(
            context.get("smm"), "record_tradeoff",
            (topic, chosen, rejected, reason),
            (topic, str(chosen), str(rejected)),
            (topic, str(chosen)),
        )

    def __repr__(self) -> str:  # pragma: no cover - confort debug
        return f"<{type(self).__name__} role={self.role.value}>"
