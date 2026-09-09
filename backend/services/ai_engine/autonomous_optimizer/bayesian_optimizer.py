"""BayesianOptimizer — surrogate ridge + exploration autour du meilleur."""
from __future__ import annotations

import random
from typing import Any

import numpy as np
from shared.utilities import get_logger

log = get_logger("ai_engine.opt.bayesian")


class BayesianOptimizer:
    """Optimiseur bayésien simplifié :

    - régression ridge numpy sur features→score comme surrogate ;
    - `suggest()` explore autour du meilleur point observé ;
    - `observe()` enrichit l'historique (params, score).
    """

    def __init__(self, n_init: int = 5, ridge_lambda: float = 1e-3,
                 seed: int = 0) -> None:
        self.n_init = max(1, n_init)
        self.ridge_lambda = ridge_lambda
        self.rng = random.Random(seed)
        self._X: list[np.ndarray] = []
        self._y: list[float] = []
        self._params: list[dict[str, Any]] = []
        self._w: np.ndarray | None = None
        self._b: float = 0.0

    # -------------------------------------------------------------- observe
    def observe(self, params: dict[str, Any], score: float) -> None:
        """Enregistre un point (params → features, score)."""
        self._params.append(dict(params))
        self._X.append(self._featurize(params))
        self._y.append(float(score))
        self._fit()
        log.debug("BO observe: n=%d score=%.4f", len(self._y), score)

    @staticmethod
    def _featurize(params: dict[str, Any]) -> np.ndarray:
        """Features numériques stables depuis un dict de params."""
        keys = sorted(params.keys())
        vals: list[float] = []
        for k in keys:
            v = params[k]
            if isinstance(v, (bool, int, float)):
                vals.append(float(v))
            else:
                vals.append(float(hash(str(v)) % 1000) / 1000.0)
        # dims fixes : pad/tronque à 8
        vals = (vals + [0.0] * 8)[:8]
        return np.array(vals, dtype=np.float64)

    # ------------------------------------------------------------------ fit
    def _fit(self) -> None:
        if len(self._y) < 2:
            return
        X = np.array(self._X)
        y = np.array(self._y)
        # ridge closed-form : w = (XᵀX + λI)⁻¹ Xᵀ y
        A = X.T @ X + self.ridge_lambda * np.eye(X.shape[1])
        try:
            self._w = np.linalg.solve(A, X.T @ y)
            self._b = float(np.mean(y - X @ self._w))
        except np.linalg.LinAlgError:
            self._w = None

    def _predict(self, features: np.ndarray) -> float:
        if self._w is None:
            return float(np.mean(self._y)) if self._y else 0.0
        return float(features @ self._w + self._b)

    # --------------------------------------------------------------- suggest
    def suggest(self, history: list[dict[str, Any]] | None = None
                ) -> dict[str, Any]:
        """Suggère les params suivants : perturbation autour du meilleur.

        `history` (optionnel) : [{params, score}] — enrichit l'observe.
        """
        if history:
            for item in history:
                if "params" in item and "score" in item:
                    self.observe(item["params"], item["score"])

        if len(self._y) < self.n_init or self._w is None:
            # phase d'exploration initiale aléatoire
            return {
                "mutation_mm": round(self.rng.uniform(0.5, 3.0), 3),
                "move_scale": round(self.rng.uniform(0.5, 2.5), 3),
                "rot_enabled": self.rng.random() < 0.5,
            }

        best_i = int(np.argmax(self._y))
        best_params = self._params[best_i]
        # exploitation : voisinage du meilleur + prédiction locale
        suggestion = dict(best_params)
        for k in list(suggestion.keys()):
            v = suggestion[k]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                sigma = max(0.05, abs(v) * 0.15)
                suggestion[k] = round(float(v) + self.rng.gauss(0.0, sigma), 3)
        return suggestion

    # ----------------------------------------------------------------- info
    def best_observed(self) -> tuple[dict[str, Any] | None, float]:
        """Meilleur point observé."""
        if not self._y:
            return None, float("-inf")
        i = int(np.argmax(self._y))
        return self._params[i], self._y[i]
