"""Surrogate neuronal (numpy) — MLP 2 couches à gradient manuel.

Apprend à prédire les sorties des simulations (ex. température max) à partir
des features du design (n_comp, densité, puissance totale, longueur filaire).
Standardisation interne (mu/sigma) conservée dans la sauvegarde npz.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import numpy as np

from shared.utilities import get_logger

log = get_logger("simulator.surrogate")


class NeuralSurrogate:
    """MLP 2 couches (tanh + linéaire), régression MSE, entraînable en numpy."""

    def __init__(self, name: str = "surrogate", n_inputs: int = 4,
                 n_hidden: int = 16, seed: int = 0) -> None:
        self.name = str(name)
        self.n_inputs = int(n_inputs)
        self.n_hidden = int(n_hidden)
        rng = np.random.default_rng(seed)
        # Xavier-like
        self.W1 = rng.standard_normal((n_hidden, n_inputs)) * np.sqrt(2.0 / (n_inputs + n_hidden))
        self.b1 = np.zeros(n_hidden)
        self.W2 = rng.standard_normal((1, n_hidden)) * np.sqrt(2.0 / n_hidden)
        self.b2 = np.zeros(1)
        self.mu = np.zeros(n_inputs)
        self.sigma = np.ones(n_inputs)
        self.y_mean = 0.0
        self.y_std = 1.0
        self.trained = False
        self.loss_history: list[float] = []

    # ---------------------------------------------------------------- forward
    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mu) / np.maximum(self.sigma, 1e-9)

    def _forward(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Retourne (sortie, couche cachée activée)."""
        hidden = np.tanh(Xs @ self.W1.T + self.b1)     # (n, H)
        out = hidden @ self.W2.T + self.b2             # (n, 1)
        return out, hidden

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Prédiction pour X (n, n_inputs) — vecteur (n,) en unités réelles."""
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        out, _ = self._forward(self._standardize(X))
        return out.ravel() * self.y_std + self.y_mean

    # --------------------------------------------------------------------- fit
    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 50,
            lr: float = 1e-3) -> "NeuralSurrogate":
        """Entraînement par descente de gradient manuelle (MSE)."""
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        y = np.asarray(y, dtype=np.float64).ravel()
        if len(X) != len(y):
            raise ValueError("X et y doivent avoir le même nombre d'échantillons")
        if len(X) < 2:
            log.warning("%s : <2 échantillons, entraînement sauté", self.name)
            return self
        # standardisation apprise sur les données
        self.mu = X.mean(axis=0)
        self.sigma = X.std(axis=0)
        self.sigma[self.sigma < 1e-9] = 1.0
        Xs = self._standardize(X)
        ys = ((y - y.mean()) / (y.std() or 1.0)).reshape(-1, 1)
        self.y_mean, self.y_std = float(y.mean()), float(y.std() or 1.0)

        n = len(Xs)
        self.loss_history = []
        for _ in range(max(1, epochs)):
            out, hidden = self._forward(Xs)                       # (n,1)
            error = out - ys                                       # (n,1)
            loss = float(np.mean(error ** 2))
            self.loss_history.append(loss)
            # gradients (MSE, tanh hidden)
            d_out = 2.0 * error / n                                # (n,1)
            dW2 = d_out.T @ hidden                                 # (1,H)
            db2 = d_out.sum(axis=0)                                # (1,)
            d_hidden = (d_out @ self.W2) * (1.0 - hidden ** 2)     # (n,H)
            dW1 = d_hidden.T @ Xs                                  # (H,in)
            db1 = d_hidden.sum(axis=0)                             # (H,)
            self.W2 -= lr * dW2
            self.b2 -= lr * db2
            self.W1 -= lr * dW1
            self.b1 -= lr * db1
        self.trained = True
        log.info("surrogate %s entraîné : %d époques, perte %.6f → %.6f",
                 self.name, epochs, self.loss_history[0], self.loss_history[-1])
        return self

    # ------------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        """Sauvegarde npz (poids + standardisation + méta)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.savez(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2,
                 mu=self.mu, sigma=self.sigma,
                 y_mean=np.array([self.y_mean]), y_std=np.array([self.y_std]),
                 name=np.array([self.name]),
                 trained=np.array([self.trained]))

    @classmethod
    def load(cls, path: str) -> "NeuralSurrogate":
        """Charge un npz sauvegardé par `save`."""
        data = np.load(path, allow_pickle=False)
        name = str(data["name"][0]) if "name" in data else "surrogate"
        dummy = cls(name=name, n_inputs=data["W1"].shape[1],
                    n_hidden=data["W1"].shape[0])
        dummy.W1, dummy.b1 = data["W1"], data["b1"]
        dummy.W2, dummy.b2 = data["W2"], data["b2"]
        dummy.mu, dummy.sigma = data["mu"], data["sigma"]
        dummy.y_mean = float(data["y_mean"][0]) if "y_mean" in data else 0.0
        dummy.y_std = float(data["y_std"][0]) if "y_std" in data else 1.0
        dummy.trained = bool(data["trained"][0]) if "trained" in data else True
        return dummy
