"""World Model V3-enrichi — encodeur, dynamique d'ensemble MLP, récompense
apprise, rollout MPC, incertitude épistémique, attribution de features.

Niveaux de capacités (cadrage demandé) :
  * noyau          : encoder 16 features, dynamics(state, action), reward predictor,
                     apprentissage linéaire (compat `fit_transition`).
  * best-to-have   : ensemble de K dynamiques MLP (numpy pur, gradients manuels)
                     → moyenne (précision) + écart-type (incertitude épistémique) ;
                     récompense APPRISE depuis les transitions réelles (MSE) ;
                     planification par rollout (MPC greedy depth-D, gamma).
  * good-to-have   : bruit d'observation pendant l'imagination (anti-surconfiance),
                     attribution de features par gradient×input, stats d'usage,
                     persistance npz rétro-compatible (anciens .npz linéaires).

100 % numpy — torch optionnel, jamais requis.
"""
from __future__ import annotations

import os
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from shared.utilities import get_logger

log = get_logger("ai_engine.rl.world_model")

FEATURE_DIM = 16
CONFIDENCE_RAMP = 200          # transitions pour atteindre la confiance max
MAX_CONFIDENCE = 0.85          # poids max du modèle appris vs heuristique


def state_from_graph(graph) -> Dict:  # noqa: ANN001 — duck-typing DesignGraph
    """Construit un dict d'état standard depuis un DesignGraph."""
    comps = list(getattr(graph, "components", {}).values())
    nets = list(getattr(graph, "nets", {}).values())
    xs = [c.x for c in comps] or [0.0]
    ys = [c.y for c in comps] or [0.0]
    return {
        "n_components": len(comps),
        "n_nets": len(nets),
        "n_routed": sum(1 for n in nets if getattr(n, "routed", False)),
        "wire_length": float(graph.total_wire_length()) if comps else 0.0,
        "violations": 0,
        "board_w": 60.0,
        "board_h": 40.0,
        "components": [
            {
                "x": c.x, "y": c.y,
                "rotation": getattr(c, "rotation", 0.0),
                "bbox_w": getattr(c, "bbox", (1.0, 0.5))[0],
                "bbox_h": getattr(c, "bbox", (1.0, 0.5))[1],
                "power_w": getattr(c, "power_w", 0.0),
                "placed": bool(getattr(c, "placed", True)),
            }
            for c in comps
        ],
        "mean_x": float(np.mean(xs)),
        "mean_y": float(np.mean(ys)),
        "std_x": float(np.std(xs)),
        "std_y": float(np.std(ys)),
    }


class _MLP:
    """MLP 2 couches (tanh + linéaire) multi-sorties, gradients numpy manuels."""

    def __init__(self, n_in: int, n_hidden: int, n_out: int, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        self.W1 = rng.standard_normal((n_hidden, n_in)) * np.sqrt(2.0 / (n_in + n_hidden))
        self.b1 = np.zeros(n_hidden)
        self.W2 = rng.standard_normal((n_out, n_hidden)) * np.sqrt(2.0 / n_hidden)
        self.b2 = np.zeros(n_out)
        self.loss_history: List[float] = []

    def forward(self, Xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        hidden = np.tanh(Xs @ self.W1.T + self.b1)
        out = hidden @ self.W2.T + self.b2
        return out, hidden

    def predict(self, X: np.ndarray) -> np.ndarray:
        out, _ = self.forward(np.atleast_2d(np.asarray(X, dtype=np.float64)))
        return out

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 80, lr: float = 2e-3,
            batch: int = 32) -> float:
        """Descente de gradient mini-batch (MSE). Retourne la perte finale."""
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        y = np.atleast_2d(np.asarray(y, dtype=np.float64))
        if len(X) != len(y) or len(X) == 0:
            return float("nan")
        n = len(X)
        self.loss_history = []
        rng = np.random.default_rng(0)
        last = float("nan")
        for _ in range(max(1, epochs)):
            idx = rng.permutation(n) if n > batch else np.arange(n)
            for start in range(0, len(idx), batch):
                sel = idx[start:start + batch]
                xb, yb = X[sel], y[sel]
                out, hidden = self.forward(xb)
                err = out - yb
                m = len(sel)
                last = float(np.mean(err ** 2))
                d_out = 2.0 * err / m
                dW2 = d_out.T @ hidden
                db2 = d_out.sum(axis=0)
                d_hidden = (d_out @ self.W2) * (1.0 - hidden ** 2)
                dW1 = d_hidden.T @ xb
                db1 = d_hidden.sum(axis=0)
                self.W2 -= lr * dW2
                self.b2 -= lr * db2
                self.W1 -= lr * dW1
                self.b1 -= lr * db1
            self.loss_history.append(last)
        return last

    def input_gradient(self, x: np.ndarray) -> np.ndarray:
        """Gradient de la sortie (somme) par rapport à l'entrée — attribution."""
        x = np.asarray(x, dtype=np.float64).ravel()
        z1 = self.W1 @ x + self.b1
        h = np.tanh(z1)
        # d(sum(out))/dx = 1ᵀ·W2·diag(1-h²)·W1
        g = self.W2.sum(axis=0) * (1.0 - h ** 2)
        return self.W1.T @ g


class WorldModel:
    """Modèle du monde V3 : encoder / ensemble dynamics / récompense apprise /
    rollout MPC / incertitude / attribution (numpy pur)."""

    def __init__(self, feature_dim: int = FEATURE_DIM, seed: int = 0,
                 hidden: int = 32, ensemble_size: int = 3,
                 rollout_noise: float = 0.01) -> None:
        self.feature_dim = int(feature_dim)
        self.hidden = int(hidden)
        self.ensemble_size = max(1, int(ensemble_size))
        self.rollout_noise = float(rollout_noise)
        # prior linéaire (rétro-compat + régularisation douce)
        rng = np.random.default_rng(seed)
        self.W: np.ndarray = np.eye(feature_dim) + 0.01 * rng.standard_normal(
            (feature_dim, feature_dim))
        self.b: np.ndarray = np.zeros(feature_dim, dtype=np.float64)
        self.violation_weight: float = 10.0
        # ensemble de dynamiques + réseau de récompense (best-to-have)
        self._ens: List[_MLP] = [
            _MLP(feature_dim, hidden, feature_dim, seed=seed * 97 + k)
            for k in range(self.ensemble_size)
        ]
        self._reward = _MLP(feature_dim, hidden, 1, seed=seed * 131 + 7)
        self._buf: Deque[Tuple[np.ndarray, np.ndarray, float]] = deque(maxlen=5000)
        self._dyn_trained = False
        self._reward_trained = False
        self._n_transitions_ref = 0      # référence de confiance (persistée)
        self.last_uncertainty: Dict[str, float] = {}
        self._torch_model: Optional[object] = None
        self.stats = {"dynamics_calls": 0, "rollouts": 0, "transitions": 0,
                      "train_calls": 0}

    # -------------------------------------------------------------- encoder
    def encoder(self, state: Dict) -> np.ndarray:
        """Vectorise un état → np.ndarray[feature_dim]."""
        comps: List[Dict] = state.get("components", [])
        board_w = float(state.get("board_w", 60.0)) or 1.0
        board_h = float(state.get("board_h", 40.0)) or 1.0
        n = max(1, state.get("n_components", len(comps)))
        n_nets = max(1, state.get("n_nets", 1))
        area = sum(c.get("bbox_w", 1.0) * c.get("bbox_h", 0.5) for c in comps)
        density = min(1.0, area / (board_w * board_h)) if comps else 0.0
        wl = float(state.get("wire_length", 0.0))
        wl_norm = wl / (10.0 * n_nets)
        n_placed = sum(1 for c in comps if c.get("placed", True))
        powers = [c.get("power_w", 0.0) for c in comps]
        rots = [float(c.get("rotation", 0.0)) % 360 for c in comps]
        aspects = [(c.get("bbox_w", 1.0) / max(1e-6, c.get("bbox_h", 0.5)))
                   for c in comps]

        feats = np.array([
            state.get("n_components", len(comps)) / 50.0,
            state.get("n_nets", 1) / 100.0,
            density,
            wl_norm,
            state.get("violations", 0) / 20.0,
            float(np.mean([c.get("x", 0.0) for c in comps] or [0.0])) / board_w,
            float(np.mean([c.get("y", 0.0) for c in comps] or [0.0])) / board_h,
            float(np.std([c.get("x", 0.0) for c in comps] or [0.0])) / board_w,
            float(np.std([c.get("y", 0.0) for c in comps] or [0.0])) / board_h,
            (float(np.mean(rots)) if rots else 0.0) / 360.0,
            (state.get("n_routed", 0) / n_nets),
            (float(np.mean(powers)) if powers else 0.0) / 5.0,
            float(np.sum(powers)) / 20.0,
            (float(np.mean(aspects)) if aspects else 0.0) / 4.0,
            n_placed / n,
            (board_w * board_h) / 5000.0,
        ], dtype=np.float64)
        return feats[:self.feature_dim]

    # ------------------------------------------------------------- dynamics
    def _apply_action_heuristic(self, state: Dict, action) -> Dict:  # noqa: ANN001
        """Effet mécanique attendu de l'action (avant correction apprise)."""
        nxt = {k: (v.copy() if isinstance(v, list) else v)
               for k, v in state.items()}
        kind = getattr(getattr(action, "kind", None), "value", str(getattr(action, "kind", "")))
        comps = nxt.get("components", [])

        if kind == "move" and comps:
            dx, dy = float(getattr(action, "dx", 0.0)), float(getattr(action, "dy", 0.0))
            moved_wl = nxt.get("wire_length", 0.0) + 0.3 * (abs(dx) + abs(dy)) * max(
                1, nxt.get("n_nets", 1))
            nxt["wire_length"] = max(0.0, moved_wl * 0.98)
            nxt["mean_x"] = nxt.get("mean_x", 0.0) + dx / max(1, len(comps))
            nxt["mean_y"] = nxt.get("mean_y", 0.0) + dy / max(1, len(comps))
        elif kind == "rotate":
            nxt["violations"] = nxt.get("violations", 0)  # rotation ~ neutre
        elif kind == "swap":
            nxt["wire_length"] = max(0.0, nxt.get("wire_length", 0.0) * 0.995)
        return nxt

    def _blend_learned(self, f_actioned: np.ndarray) -> Tuple[np.ndarray, float]:
        """Mélange prior heuristique ↔ prédiction d'ensemble. Retourne (f, α)."""
        if not self._dyn_trained:
            return f_actioned, 0.0
        alpha = min(MAX_CONFIDENCE,
                    max(self._n_transitions_ref, len(self._buf)) / CONFIDENCE_RAMP)
        preds = np.stack([m.predict(f_actioned)[0] for m in self._ens])
        f_mean = preds.mean(axis=0)
        f_std = preds.std(axis=0)
        self.last_uncertainty = {
            "max_std": float(f_std.max()),
            "mean_std": float(f_std.mean()),
            "alpha": float(alpha),
        }
        return (1.0 - alpha) * f_actioned + alpha * f_mean, alpha

    @staticmethod
    def _write_back(state: Dict, f: np.ndarray) -> None:
        """Réinjecte wire_length / violations depuis le vecteur de features."""
        n_nets = max(1, state.get("n_nets", 1))
        state["wire_length"] = max(0.0, float(f[3]) * 10.0 * n_nets)
        state["violations"] = max(0, int(round(float(f[4]) * 20.0)))

    def dynamics(self, state: Dict, action) -> Dict:  # noqa: ANN001
        """Prochain état imaginé : heuristique d'action + correction d'ensemble.

        Après appel, `self.last_uncertainty` porte l'écart-type inter-membres
        (incertitude épistémique) du dernier pas.
        """
        self.stats["dynamics_calls"] += 1
        nxt = self._apply_action_heuristic(state, action)
        f_a = self.encoder(nxt)
        f_next, _alpha = self._blend_learned(f_a)
        self._write_back(nxt, f_next)
        return nxt

    # ---------------------------------------------------- reward predictor
    def reward_predictor(self, state: Dict) -> float:  # noqa: ANN001
        """Récompense prédite : réseau appris si entraîné, sinon analytique."""
        f = self.encoder(state)
        if self._reward_trained:
            return float(self._reward.predict(f)[0][0])
        wl_norm = float(f[3])
        viol = float(f[4])
        return -(wl_norm + viol * self.violation_weight)

    # ------------------------------------------------------------- planning
    def rollout(self, state: Dict, actions: Sequence,  # noqa: ANN001
                depth: int = 2, gamma: float = 0.95,
                noise: Optional[float] = None) -> List[Tuple[Any, float]]:
        """Imagine chaque action candidate sur `depth` pas (chaîne glissante
        simple : répétition de la même action) et retourne [(action, valeur)]
        triée par valeur décroissante. Bruit d'observation optionnel."""
        self.stats["rollouts"] += 1
        sigma = self.rollout_noise if noise is None else float(noise)
        rng = np.random.default_rng(0)
        scored: List[Tuple[Any, float]] = []
        for action in actions:
            cur = state
            value = 0.0
            discount = 1.0
            for _ in range(max(1, depth)):
                cur = self.dynamics(cur, action)
                r = self.reward_predictor(cur)
                if sigma > 0.0:
                    r += float(rng.normal(0.0, sigma))
                value += discount * r
                discount *= gamma
            scored.append((action, value))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored

    def plan(self, state: Dict, actions: Sequence, depth: int = 2,  # noqa: ANN001
             gamma: float = 0.95) -> Optional[Any]:
        """Meilleure action selon le rollout (MPC greedy)."""
        scored = self.rollout(state, actions, depth=depth, gamma=gamma)
        return scored[0][0] if scored else None

    # -------------------------------------------------------------- learning
    def record_transition(self, state: Dict, action, next_state: Dict,  # noqa: ANN001
                          reward: float) -> None:
        """Enregistre une transition réelle (f_actioned → f_next, reward)."""
        f_a = self.encoder(self._apply_action_heuristic(state, action))
        f_next = self.encoder(next_state)
        self._buf.append((f_a, f_next, float(reward)))
        self._n_transitions_ref = len(self._buf)
        self.stats["transitions"] = len(self._buf)

    def train(self, epochs: int = 80, lr: float = 2e-3,
              batch: int = 32) -> Dict[str, float]:
        """Entraîne l'ensemble (bagging par membre) + la récompense.

        Retourne {dyn_mse_k, dyn_mse_mean, reward_mse, n_transitions}.
        """
        self.stats["train_calls"] += 1
        if len(self._buf) < 4:
            log.info("world_model.train : %d transitions (<4), ignoré", len(self._buf))
            return {"n_transitions": float(len(self._buf))}
        X = np.stack([t[0] for t in self._buf])
        Y = np.stack([t[1] for t in self._buf])
        R = np.array([t[2] for t in self._buf], dtype=np.float64)
        out: Dict[str, float] = {"n_transitions": float(len(self._buf))}
        rng = np.random.default_rng(0)
        losses: List[float] = []
        for k, member in enumerate(self._ens):
            idx = rng.integers(0, len(X), size=len(X))     # bootstrap (bagging)
            mse = member.fit(X[idx], Y[idx], epochs=epochs, lr=lr, batch=batch)
            losses.append(mse)
            out[f"dyn_mse_{k}"] = round(float(mse), 6)
        out["dyn_mse_mean"] = round(float(np.mean(losses)), 6)
        r_mse = self._reward.fit(Y, R.reshape(-1, 1), epochs=epochs, lr=lr, batch=batch)
        out["reward_mse"] = round(float(r_mse), 6)
        self._dyn_trained = True
        self._reward_trained = True
        log.info("world_model entraîné : %d transitions, dyn MSE %.6f, reward MSE %.6f",
                 len(self._buf), out["dyn_mse_mean"], out["reward_mse"])
        return out

    def fit_transition(self, features: np.ndarray, features_next: np.ndarray,
                       lr: float = 1e-3) -> float:
        """Compat V3-initiale : ajuste le prior linéaire sur une transition."""
        target = features_next
        pred = self.W @ features + self.b
        err = target - pred
        grad_W = np.outer(err, features)
        self.W += lr * grad_W
        self.b += lr * err
        return float(np.mean(err ** 2))

    # ----------------------------------------------------------- explainabilité
    def feature_attribution(self, state: Dict) -> Dict[str, float]:  # noqa: ANN001
        """Attribution gradient×input de la récompense par feature (top dict).
        Retourne un dict {index: importance} normalisé (somme = 1)."""
        f = self.encoder(state)
        grads = np.stack([m.input_gradient(f) for m in self._ens]).mean(axis=0)
        attrib = np.abs(grads * f)
        total = attrib.sum()
        if total < 1e-12:
            return {}
        norm = attrib / total
        return {f"f{i}": float(v) for i, v in enumerate(norm) if v > 1e-3}

    # ---------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        """Sauvegarde prior linéaire + ensemble + récompense en npz."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload: Dict[str, np.ndarray] = {"W": self.W, "b": self.b}
        for k, m in enumerate(self._ens):
            payload[f"W1_{k}"] = m.W1
            payload[f"b1_{k}"] = m.b1
            payload[f"W2_{k}"] = m.W2
            payload[f"b2_{k}"] = m.b2
        payload["rW1"] = self._reward.W1
        payload["rb1"] = self._reward.b1
        payload["rW2"] = self._reward.W2
        payload["rb2"] = self._reward.b2
        payload["meta"] = np.array([self.feature_dim, self.hidden,
                                    self.ensemble_size,
                                    int(self._dyn_trained),
                                    int(self._reward_trained),
                                    int(self._n_transitions_ref)])
        np.savez(path, **payload)

    def load(self, path: str) -> bool:
        """Charge un npz (nouveau format ensemble ou ancien format linéaire)."""
        if not os.path.exists(path):
            return False
        try:
            data = np.load(path)
            if "W" in data:
                self.W, self.b = data["W"], data["b"]
            if "meta" in data:
                meta = [int(v) for v in data["meta"]]
                fd, hidden, k, dyn_t, rew_t = meta[:5]
                n_ref = meta[5] if len(meta) > 5 else 0
                if fd == self.feature_dim and hidden == self.hidden and k == self.ensemble_size:
                    self._dyn_trained = bool(dyn_t)
                    self._reward_trained = bool(rew_t)
                    self._n_transitions_ref = int(n_ref)
                    for i, m in enumerate(self._ens):
                        m.W1, m.b1 = data[f"W1_{i}"], data[f"b1_{i}"]
                        m.W2, m.b2 = data[f"W2_{i}"], data[f"b2_{i}"]
                    self._reward.W1, self._reward.b1 = data["rW1"], data["rb1"]
                    self._reward.W2, self._reward.b2 = data["rW2"], data["rb2"]
                    log.info("world_model chargé (ensemble %d, dyn=%s, reward=%s)",
                             k, self._dyn_trained, self._reward_trained)
                    return True
            return True      # ancien format linéaire chargé
        except (OSError, KeyError, ValueError) as exc:
            log.warning("WorldModel.load(%s) échoué: %s", path, exc)
            return False
