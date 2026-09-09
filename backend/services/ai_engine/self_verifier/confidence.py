"""Scorer de confiance — agrège les issues en un score global 0..1."""
from __future__ import annotations

from typing import Any

from shared.utilities import get_logger

log = get_logger("ai_engine.verify.confidence")

# pénalités par sévérité
_PENALTY = {"error": 0.35, "warning": 0.08, "info": 0.02}
_BONUS_ALL_ROUTED = 0.05


class ConfidenceScorer:
    """Confiance du design = 1.0 − Σ pénalités + bonus, clampé [0,1]."""

    def __init__(self, penalty_error: float = _PENALTY["error"],
                 penalty_warning: float = _PENALTY["warning"],
                 penalty_info: float = _PENALTY["info"]) -> None:
        self.penalties = {"error": penalty_error,
                          "warning": penalty_warning, "info": penalty_info}

    def score(self, graph, issues: list[dict[str, Any]]) -> float:  # noqa: ANN001
        """Score de confiance global du graphe face à ses issues."""
        score = 1.0
        by_kind: dict[str, int] = {}
        for issue in issues:
            sev = str(issue.get("severity", "info")).lower()
            score -= self.penalties.get(sev, 0.02)
            k = str(issue.get("kind", "?"))
            by_kind[k] = by_kind.get(k, 0) + 1

        # bonus si tout est routé
        try:
            unrouted = list(graph.unrouted_nets() or [])
            if not unrouted and getattr(graph, "nets", None):
                score += _BONUS_ALL_ROUTED
        except Exception:
            pass

        final = max(0.0, min(1.0, score))
        log.debug("confidence=%.3f issues=%s", final, by_kind)
        return round(final, 4)
