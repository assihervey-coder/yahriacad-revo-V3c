"""Value Network — estimation V(s) par régression MSE (numpy pur)."""
from __future__ import annotations

import os

import numpy as np
from shared.utilities import get_logger

log = get_logger("ai_engine.rl.value")


class ValueNetwork:
    """V(s) = w·f + b — entraîné par descente de gradient MSE.

    Peut servir de baseline pour réduire la variance de REINFORCE.
    """

    def __init__(self, feature_dim: int = 16, seed: int = 0) -> None:
        self.feature_dim = int(feature_dim)
        rng = np.random.default_rng(seed)
        self.w: np.ndarray = rng.standard_normal(feature_dim) * 0.01
        self.b: float = 0.0

    def estimate(self, features: np.ndarray) -> float:
        """Valeur estimée de l'état."""
        f = np.asarray(features, dtype=np.float64).ravel()
        return float(f @ self.w + self.b)

    def train_batch(self, features: np.ndarray, returns: np.ndarray,
                    lr: float = 1e-3) -> float:
        """Descente MSE : w ← w − lr·∇(v−y)². Retourne la MSE moyenne."""
        f = np.asarray(features, dtype=np.float64)
        y = np.asarray(returns, dtype=np.float64).ravel()
        if f.ndim == 1:
            f = f[None, :]
        preds = f @ self.w + self.b
        errors = preds - y
        grad_w = (2.0 / len(f)) * (f.T @ errors)
        grad_b = (2.0 / len(f)) * float(np.sum(errors))
        self.w -= lr * grad_w
        self.b -= lr * grad_b
        return float(np.mean(errors ** 2))

    def save(self, path: str) -> None:
        """Sauvegarde npz."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.savez(path, w=self.w, b=np.array([self.b]))

    def load(self, path: str) -> bool:
        """Charge npz — True si succès."""
        if not os.path.exists(path):
            return False
        try:
            data = np.load(path)
            w = data["w"]
            if w.shape != self.w.shape:
                log.warning("ValueNetwork.load: shape %s != %s", w.shape, self.w.shape)
                return False
            self.w, self.b = w, float(data["b"][0])
            return True
        except (OSError, KeyError, ValueError) as exc:
            log.warning("ValueNetwork.load(%s) échoué: %s", path, exc)
            return False
