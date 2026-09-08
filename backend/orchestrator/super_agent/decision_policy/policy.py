"""Politique de décision — machine à états des phases du design PCB.

Transitions canoniques : parse → select → place → route → verify → simulate →
optimize → export → done, avec rollback ciblé (verification failed + retries > 0)
et escalation (retries épuisés ou confidence < 0.4).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.utilities import get_logger

log = get_logger("super_agent.policy")

PHASE_ORDER: List[str] = [
    "parse", "select", "place", "route", "verify", "simulate", "optimize", "export", "done",
]

# Cible de rollback par phase courante (on remonte à l'agent qui peut réparer)
ROLLBACK_TARGET: Dict[str, str] = {
    "verify": "route",
    "simulate": "route",
    "route": "place",
    "optimize": "place",
    "place": "select",
    "select": "select",
    "export": "optimize",
}

CONFIDENCE_ESCALATION_THRESHOLD = 0.4
QUALITY_OPTIMIZE_THRESHOLD = 0.85


class DecisionPolicy:
    """Machine à états déterministe — utilisée par le SuperAgent (fallback LLM)."""

    def next_phase(self, current: str, signals: Optional[Dict[str, Any]] = None) -> str:
        """Phase suivante selon l'état courant et les signaux d'exécution."""
        signals = signals or {}
        if current == "done":
            return "done"
        if self.should_rollback(signals):
            target = ROLLBACK_TARGET.get(current, "place")
            log.debug("rollback %s → %s", current, target)
            return target
        if self.should_escalate(signals):
            return "escalate"
        if current not in PHASE_ORDER or not current:
            return "parse"
        index = PHASE_ORDER.index(current)
        if index >= len(PHASE_ORDER) - 1:
            return "done"
        nxt = PHASE_ORDER[index + 1]
        if nxt == "optimize" and not self.should_optimize(signals):
            nxt = "export"
        return nxt

    # ------------------------------------------------------------- conditions
    def should_rollback(self, signals: Dict[str, Any]) -> bool:
        """Vérification échouée ET budget de retry disponible."""
        failed = not signals.get("verification_passed", True)
        retries_left = int(signals.get("retries_left", 0) or 0)
        return bool(failed and retries_left > 0)

    def should_escalate(self, signals: Dict[str, Any]) -> bool:
        """Retries épuisés sur échec, ou confiance globale < 0.4."""
        failed = not signals.get("verification_passed", True)
        retries_left = int(signals.get("retries_left", 0) or 0)
        if failed and retries_left <= 0:
            return True
        try:
            confidence = float(signals.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        return confidence < CONFIDENCE_ESCALATION_THRESHOLD

    def should_optimize(self, signals: Dict[str, Any]) -> bool:
        """L'optimisation est utile si la vérification passe et la qualité < seuil."""
        if not signals.get("verification_passed", True):
            return False
        if signals.get("optimize_requested"):
            return True
        quality = signals.get("quality")
        if quality is None:
            return True
        try:
            return float(quality) / (100.0 if float(quality) > 1.0 else 1.0) < QUALITY_OPTIMIZE_THRESHOLD
        except (TypeError, ValueError):
            return True
