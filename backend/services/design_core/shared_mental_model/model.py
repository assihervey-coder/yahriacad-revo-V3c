"""🔥 SharedMentalModel — mémoire de contexte commune à tous les agents.

Le modèle mental partagé est l'espace où LLM (symbolique), RL (décision),
simulateurs (physique), DRC/DFM, éditeur humain et manufacturing déposent et
relisent : faits de contexte, décisions justifiées, arbitrages (tradeoffs) et
niveaux de confiance par domaine. Il alimente notamment les prompts LLM via
`export_for_llm()`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from services.design_core.design_graph.graph import DesignGraph
from services.design_core.intent_graph.intent_graph import IntentGraph

# Pondération de confiance par domaine (le physique a plus de poids).
DOMAIN_WEIGHTS: dict[str, float] = {
    "physical": 1.5, "simulation": 1.5, "verification": 1.3, "human": 1.2,
    "design": 1.0, "placement": 1.0, "routing": 1.0, "general": 1.0,
}
DEFAULT_CONFIDENCE = 0.5


@dataclass
class DecisionRecord:
    """Décision prise par un agent (ou un humain) avec sa justification."""

    actor: str
    decision: str
    rationale: str
    confidence: float
    ts: float
    domain: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor, "decision": self.decision, "rationale": self.rationale,
            "confidence": self.confidence, "ts": self.ts, "domain": self.domain,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionRecord:
        return cls(
            actor=str(d.get("actor", "")), decision=str(d.get("decision", "")),
            rationale=str(d.get("rationale", "")), confidence=float(d.get("confidence", 0.5) or 0.5),
            ts=float(d.get("ts", 0.0) or 0.0), domain=str(d.get("domain", "general") or "general"),
        )


@dataclass
class Tradeoff:
    """Arbitrage entre deux critères : ce qui a été choisi et son poids."""

    criterion_a: str
    criterion_b: str
    chose: str                    # "a" | "b" | description libre du compromis
    weight: float                 # 0..1 (0 = 100% b, 1 = 100% a)
    ts: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_a": self.criterion_a, "criterion_b": self.criterion_b,
            "chose": self.chose, "weight": self.weight, "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Tradeoff:
        return cls(
            criterion_a=str(d.get("criterion_a", "")), criterion_b=str(d.get("criterion_b", "")),
            chose=str(d.get("chose", "")), weight=float(d.get("weight", 0.5) or 0.5),
            ts=float(d.get("ts", 0.0) or 0.0),
        )


class ConfidenceTracker:
    """Confiance par domaine (0..1) avec moyenne globale pondérée."""

    def __init__(self) -> None:
        self._scores: dict[str, float] = {}

    def update(self, domain: str, score: float) -> float:
        """Met à jour (clampé 0..1) la confiance d'un domaine."""
        self._scores[domain] = max(0.0, min(1.0, float(score)))
        return self._scores[domain]

    def get(self, domain: str) -> float:
        """Confiance d'un domaine (0.5 par défaut si jamais mise à jour)."""
        return self._scores.get(domain, DEFAULT_CONFIDENCE)

    def global_score(self) -> float:
        """Moyenne pondérée des domaines connus ; 0.5 si vide."""
        if not self._scores:
            return DEFAULT_CONFIDENCE
        total_w = sum(DOMAIN_WEIGHTS.get(d, 1.0) for d in self._scores)
        if total_w <= 0.0:
            return DEFAULT_CONFIDENCE
        return sum(s * DOMAIN_WEIGHTS.get(d, 1.0) for d, s in self._scores.items()) / total_w

    def report(self) -> dict[str, float]:
        """Rapport : score par domaine + 'global'."""
        out = {d: round(s, 3) for d, s in sorted(self._scores.items())}
        out["global"] = round(self.global_score(), 3)
        return out

    def to_dict(self) -> dict[str, float]:
        return dict(self._scores)

    def load(self, d: dict[str, float]) -> None:
        for domain, score in (d or {}).items():
            self.update(domain, score)


class SharedMentalModel:
    """Mémoire partagée : contexte par domaine, décisions, tradeoffs, confiance."""

    def __init__(
        self,
        graph: DesignGraph | None = None,
        intents: IntentGraph | None = None,
    ) -> None:
        self.graph = graph
        self.intents = intents
        self.confidence: ConfidenceTracker = ConfidenceTracker()
        self._context: dict[str, dict[str, Any]] = {}
        self._decisions: list[DecisionRecord] = []
        self._tradeoffs: list[Tradeoff] = []
        if graph is not None:
            self.sync_from_graph()

    # ------------------------------------------------------------------ contexte
    def update_context(self, domain: str, facts: dict[str, Any]) -> None:
        """Fusionne des faits dans le contexte d'un domaine (last-write-wins par clé)."""
        self._context.setdefault(domain, {}).update(dict(facts))

    def context(self, domain: str) -> dict[str, Any]:
        """Copie du contexte d'un domaine ({} si inconnu)."""
        return dict(self._context.get(domain, {}))

    def full_context(self) -> dict[str, dict[str, Any]]:
        """Copie de tous les contextes par domaine."""
        return {d: dict(c) for d, c in self._context.items()}

    def sync_from_graph(self) -> None:
        """Rafraîchit le domaine 'design' depuis le DesignGraph (+ 'intents')."""
        if self.graph is None:
            return
        stats = self.graph.stats()
        self.update_context("design", {
            "stats": stats,
            "board_size_mm": list(self.graph.board_size),
            "unrouted_nets": [n.net_id for n in self.graph.unrouted_nets()],
            "density": round(self.graph.utilization(), 4),
            "ts": time.time(),
        })
        if self.intents is not None:
            top = self.intents.by_priority()[:5]
            self.update_context("intents", {
                "top": [{"id": i.id, "priority": i.priority, "status": i.status,
                         "description": i.description} for i in top],
                "ts": time.time(),
            })

    # ----------------------------------------------------------------- décisions
    def record_decision(
        self,
        actor: str,
        decision: str,
        rationale: str,
        confidence: float,
        domain: str = "general",
    ) -> DecisionRecord:
        """Enregistre une décision justifiée et met à jour la confiance du domaine."""
        record = DecisionRecord(
            actor=actor, decision=decision, rationale=rationale,
            confidence=max(0.0, min(1.0, float(confidence))), ts=time.time(), domain=domain,
        )
        self._decisions.append(record)
        self.confidence.update(domain, record.confidence)
        return record

    def decisions(self) -> list[DecisionRecord]:
        """Toutes les décisions (ordre chronologique)."""
        return list(self._decisions)

    def decisions_by(
        self,
        actor: str | None = None,
        domain: str | None = None,
    ) -> list[DecisionRecord]:
        """Décisions filtrées par acteur et/ou domaine."""
        return [
            d for d in self._decisions
            if (actor is None or d.actor == actor) and (domain is None or d.domain == domain)
        ]

    # ----------------------------------------------------------------- tradeoffs
    def record_tradeoff(
        self, criterion_a: str, criterion_b: str, chose: str, weight: float = 0.5,
    ) -> Tradeoff:
        """Enregistre un arbitrage entre deux critères de conception."""
        tradeoff = Tradeoff(
            criterion_a=criterion_a, criterion_b=criterion_b, chose=chose,
            weight=max(0.0, min(1.0, float(weight))), ts=time.time(),
        )
        self._tradeoffs.append(tradeoff)
        return tradeoff

    def tradeoffs(self) -> list[Tradeoff]:
        """Tous les arbitrages enregistrés."""
        return list(self._tradeoffs)

    # ------------------------------------------------------------- sérialisation
    def snapshot(self) -> dict[str, Any]:
        """Snapshot complet (le graphe/intentions restent des références vivantes)."""
        return {
            "context": self.full_context(),
            "decisions": [d.to_dict() for d in self._decisions],
            "tradeoffs": [t.to_dict() for t in self._tradeoffs],
            "confidence": self.confidence.to_dict(),
        }

    @classmethod
    def restore(cls, d: dict[str, Any]) -> SharedMentalModel:
        """Reconstruit un SharedMentalModel depuis un snapshot (sans graphe attaché)."""
        model = cls(graph=None, intents=None)
        model._context = {str(k): dict(v) for k, v in d.get("context", {}).items()}
        model._decisions = [DecisionRecord.from_dict(x) for x in d.get("decisions", [])]
        model._tradeoffs = [Tradeoff.from_dict(x) for x in d.get("tradeoffs", [])]
        model.confidence.load(d.get("confidence", {}))
        return model

    # ------------------------------------------------------------------ pour LLM
    def export_for_llm(self) -> str:
        """Résumé texte compact destiné aux prompts LLM (intentions, état, décisions)."""
        lines: list[str] = ["=== CONTEXTE PROJET (modèle mental partagé) ==="]

        if self.intents is not None:
            lines.append("[Intentions prioritaires]")
            for intent in self.intents.by_priority()[:5]:
                lines.append(
                    f"- [{intent.id} P{intent.priority}][{intent.status}] ({intent.kind}) "
                    f"{intent.description}"
                )

        design_ctx = self._context.get("design", {})
        if design_ctx:
            lines.append("[État du design]")
            stats = design_ctx.get("stats", {})
            if stats:
                lines.append(
                    f"composants={stats.get('components', 0)} (placés={stats.get('placed', 0)}), "
                    f"nets={stats.get('nets', 0)} (routés={stats.get('routed', 0)}), "
                    f"couches={stats.get('layers', 0)}, "
                    f"longueur_pistes={stats.get('wire_length_mm', 0)}mm, "
                    f"coût={stats.get('cost_usd', 0)}$"
                )
            unrouted = design_ctx.get("unrouted_nets") or []
            if unrouted:
                lines.append(f"nets non routés: {', '.join(map(str, unrouted[:10]))}"
                             + (" ..." if len(unrouted) > 10 else ""))
            if "density" in design_ctx:
                lines.append(f"densité carte={design_ctx['density']}")

        recent = self._decisions[-5:]
        if recent:
            lines.append("[Dernières décisions]")
            for d in recent:
                lines.append(
                    f"- {d.actor}/{d.domain}: {d.decision} (confiance {d.confidence:.2f}) — {d.rationale}"
                )

        recent_t = self._tradeoffs[-5:]
        if recent_t:
            lines.append("[Arbitrages]")
            for t in recent_t:
                lines.append(
                    f"- choisi '{t.chose}' (poids {t.weight:.2f}): {t.criterion_a} vs {t.criterion_b}"
                )

        report = self.confidence.report()
        if len(report) > 1 or "global" in report:
            conf = " | ".join(f"{k}={v:.2f}" for k, v in report.items())
            lines.append(f"[Confiance] {conf}")

        return "\n".join(lines)
