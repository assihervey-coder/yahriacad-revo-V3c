"""ConvergenceMonitor — détection de convergence de la boucle multi-physique."""
from __future__ import annotations

import math

from shared.utilities import get_logger

log = get_logger("simulator.convergence")


class ConvergenceMonitor:
    """Convergé si le delta relatif (L2) reste < tolérance sur N itérations.

    `track(metrics)` ajoute un point d'historique et retourne l'état courant.
    """

    def __init__(self, tol: float = 1e-3, window: int = 3) -> None:
        self.tol = float(tol)
        self.window = int(window)
        self.history: list[dict[str, float]] = []
        self.deltas: list[float] = []

    def track(self, metrics: dict[str, float]) -> bool:
        """Ajoute un jeu de métriques numériques ; retourne True si convergé."""
        numeric = {k: float(v) for k, v in metrics.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if self.history:
            self.deltas.append(self._relative_delta(self.history[-1], numeric))
        self.history.append(numeric)
        return self.converged

    @property
    def converged(self) -> bool:
        """True si les `window` derniers deltas relatifs sont sous la tolérance."""
        if len(self.deltas) < self.window:
            return False
        return all(d < self.tol for d in self.deltas[-self.window:])

    @staticmethod
    def _relative_delta(prev: dict[str, float], cur: dict[str, float]) -> float:
        """Δ relatif L2 sur les clés communes (0.0 si norme de référence nulle)."""
        keys = [k for k in prev.keys() & cur.keys()]
        if not keys:
            return math.inf
        num = math.sqrt(sum((cur[k] - prev[k]) ** 2 for k in keys))
        den = math.sqrt(sum(prev[k] ** 2 for k in keys))
        return num / den if den > 1e-12 else (0.0 if num < 1e-12 else math.inf)

    def reset(self) -> None:
        """Réinitialise l'historique (nouvelle boucle)."""
        self.history.clear()
        self.deltas.clear()

    def summary(self) -> dict[str, float] | None:
        """Dernier delta et nb d'itérations (pour le reporting)."""
        if not self.deltas:
            return None
        return {"iterations": float(len(self.history)),
                "last_delta": self.deltas[-1]}
