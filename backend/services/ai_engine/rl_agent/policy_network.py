"""Policy Network — logits softmax (numpy) + REINFORCE, torch optionnel."""
from __future__ import annotations

import os
from typing import Optional

import numpy as np

from shared.utilities import get_logger

log = get_logger("ai_engine.rl.policy")


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Softmax stable numériquement."""
    z = logits / max(1e-6, temperature)
    z = z - np.max(z)
    e = np.exp(z)
    return e / max(1e-12, float(np.sum(e)))


class PolicyNetwork:
    """Politique linéaire numpy (MLP torch si dispo) — REINFORCE.

    logits = features @ W + b ; ∇log π(a) = (onehot(a) - π) ⊗ features.
    """

    def __init__(self, n_actions: int, feature_dim: int = 16,
                 hidden: int | None = None, seed: int = 0) -> None:
        self.n_actions = int(n_actions)
        self.feature_dim = int(feature_dim)
        rng = np.random.default_rng(seed)
        # Xavier-like init
        self.W: np.ndarray = rng.standard_normal((feature_dim, n_actions)) * \
            (1.0 / np.sqrt(feature_dim))
        self.b: np.ndarray = np.zeros(n_actions, dtype=np.float64)
        self._torch: Optional[object] = None
        self._torch_ok = self._try_torch(hidden)

    def _try_torch(self, hidden: int | None) -> bool:
        """Active le petit MLP torch si la librairie est disponible."""
        try:
            import torch  # dépendance lourde — optionnelle
            nn = torch.nn
            hidden = hidden or max(16, self.feature_dim * 2)
            model = nn.Sequential(
                nn.Linear(self.feature_dim, hidden), nn.Tanh(),
                nn.Linear(hidden, self.n_actions),
            )
            for p in model.parameters():
                p.data *= 0.1
            self._torch = model
            log.info("PolicyNetwork: backend torch activé (%d actions)", self.n_actions)
            return True
        except ImportError:
            return False

    # -------------------------------------------------------------- forward
    def forward(self, features: np.ndarray) -> np.ndarray:
        """Logits pour un vecteur de features."""
        f = np.asarray(features, dtype=np.float64).ravel()
        if self._torch is not None:
            try:
                import torch
                with torch.no_grad():
                    t = torch.as_tensor(f, dtype=torch.float32)
                    return self._torch(t).numpy().astype(np.float64)  # type: ignore[union-attr]
            except Exception as exc:  # pragma: no cover
                log.debug("torch forward échoué (%s) → numpy", exc)
        return f @ self.W + self.b

    def probs(self, features: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        """Distribution de probabilités sur les actions."""
        return softmax(self.forward(features), temperature)

    # --------------------------------------------------------------- action
    def select_action(self, features: np.ndarray, greedy: bool = False,
                      eps: float = 0.1) -> int:
        """Choisit une action : argmax (greedy) ou échantillonnage ε-greedy."""
        p = self.probs(features)
        if greedy:
            return int(np.argmax(p))
        if eps > 0 and np.random.random() < eps:
            return int(np.random.randint(self.n_actions))
        return int(np.random.choice(self.n_actions, p=p))

    # --------------------------------------------------------------- train
    def train_batch(self, features: np.ndarray, actions: np.ndarray,
                    advantages: np.ndarray, lr: float = 1e-3) -> float:
        """REINFORCE numpy : W += lr · mean(adv · (onehot - π)) ⊗ f.

        Retourne la perte (−advantage·log π) moyenne.
        """
        f = np.asarray(features, dtype=np.float64)
        a = np.asarray(actions, dtype=np.int64).ravel()
        adv = np.asarray(advantages, dtype=np.float64).ravel()
        if f.ndim == 1:
            f = f[None, :]

        losses: list[float] = []
        for fi, ai, di in zip(f, a, adv):
            p = self.probs(fi)
            onehot = np.zeros(self.n_actions)
            onehot[ai] = 1.0
            grad_logp = np.outer(onehot - p, fi)          # (n_actions, F)
            self.W += lr * di * grad_logp.T               # (F, n_actions)
            self.b += lr * di * (onehot - p)
            losses.append(-di * np.log(max(1e-12, p[ai])))
        return float(np.mean(losses)) if losses else 0.0

    # ---------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        """Sauvegarde npz (W, b) — les poids torch sont ignorés (portable)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.savez(path, W=self.W, b=self.b,
                 n_actions=np.array([self.n_actions]),
                 feature_dim=np.array([self.feature_dim]))

    def load(self, path: str) -> bool:
        """Charge npz — True si succès et dimensions compatibles."""
        if not os.path.exists(path):
            return False
        try:
            data = np.load(path)
            W, b = data["W"], data["b"]
            if W.shape != self.W.shape:
                log.warning("PolicyNetwork.load: shape %s != %s",
                            W.shape, self.W.shape)
                return False
            self.W, self.b = W, b
            return True
        except (OSError, KeyError, ValueError) as exc:
            log.warning("PolicyNetwork.load(%s) échoué: %s", path, exc)
            return False
