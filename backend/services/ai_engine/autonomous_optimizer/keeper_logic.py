"""Keeper — décide si une solution candidate remplace l'incumbent."""
from __future__ import annotations

from shared.utilities import get_logger

log = get_logger("ai_engine.opt.keeper")


class Keeper:
    """Garde-fou de l'optimisation : ne garde que les améliorations.

    - `keep(candidate, incumbent)` : True si candidate ≥ incumbent − ε ;
    - historique des scores, compteur de stagnation, critère d'arrêt.
    """

    def __init__(self, tolerance: float = 1e-6) -> None:
        self.tolerance = float(tolerance)
        self.history: list[float] = []
        self.best_score: float | None = None
        self._no_improve = 0

    def keep(self, candidate_score: float, incumbent_score: float,
             patience: int = 8) -> bool:
        """Garde la candidate UNIQUEMENT si elle améliore l'incumbent.

        Une candidate strictement meilleure est acceptée ; toute tentative
        égale ou pire est rejetée (rollback de la tentative). Le compteur de
        stagnation progresse à chaque rejet.
        `patience` est accepté pour compatibilité (l'arrêt est géré par
        `should_stop`).
        """
        self.history.append(candidate_score)
        improved = candidate_score > incumbent_score + self.tolerance
        if improved:
            if self.best_score is None or candidate_score > self.best_score:
                self.best_score = candidate_score
            self._no_improve = 0
        else:
            self._no_improve += 1
        return improved

    def stagnation_count(self) -> int:
        """Nombre d'itérations sans amélioration du meilleur score."""
        return self._no_improve

    def should_stop(self, iterations: int, no_improve: int,
                    max_iters: int = 50, patience: int = 8) -> bool:
        """Arrêt si budget épuisé ou stagnation ≥ patience."""
        if iterations >= max_iters:
            return True
        return no_improve >= patience

    def summary(self) -> dict[str, float]:
        """Statistiques d'historique (observabilité)."""
        if not self.history:
            return {"n": 0.0}
        return {
            "n": float(len(self.history)),
            "first": self.history[0],
            "best": self.best_score if self.best_score is not None else self.history[-1],
            "last": self.history[-1],
        }
