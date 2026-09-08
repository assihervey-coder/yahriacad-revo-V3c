"""World Model — encodeur d'état, dynamique approchée, prédicteur de récompense.

100 % numpy (torch optionnel non requis). Le modèle apprend une dynamique
linéaire sur les features : Δf ≈ W·f + b.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np

from shared.utilities import get_logger

log = get_logger("ai_engine.rl.world_model")

FEATURE_DIM = 16


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


class WorldModel:
    """Modèle du monde : encoder / dynamics / reward_predictor (numpy pur)."""

    def __init__(self, feature_dim: int = FEATURE_DIM, seed: int = 0) -> None:
        self.feature_dim = feature_dim
        rng = np.random.default_rng(seed)
        # dynamique linéaire initialisée proche de l'identité (stabilité)
        self.W: np.ndarray = np.eye(feature_dim) + 0.01 * rng.standard_normal(
            (feature_dim, feature_dim))
        self.b: np.ndarray = np.zeros(feature_dim, dtype=np.float64)
        self.violation_weight: float = 10.0
        self._torch_model: Optional[object] = None

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
    def dynamics(self, state: Dict, action) -> Dict:  # noqa: ANN001
        """Prochain état approché : applique l'action + correction linéaire."""
        nxt = {k: (v.copy() if isinstance(v, list) else v)
               for k, v in state.items()}
        kind = getattr(getattr(action, "kind", None), "value", str(getattr(action, "kind", "")))
        comps = nxt.get("components", [])
        ref = getattr(action, "ref", "")

        if kind == "move" and comps:
            dx, dy = float(getattr(action, "dx", 0.0)), float(getattr(action, "dy", 0.0))
            moved_wl = nxt.get("wire_length", 0.0) + 0.3 * (abs(dx) + abs(dy)) * max(
                1, nxt.get("n_nets", 1))
            # l'optimiseur réel corrigera ; le modèle suppose un léger gain net
            nxt["wire_length"] = max(0.0, moved_wl * 0.98)
            nxt["mean_x"] = nxt.get("mean_x", 0.0) + dx / max(1, len(comps))
            nxt["mean_y"] = nxt.get("mean_y", 0.0) + dy / max(1, len(comps))
        elif kind == "rotate":
            nxt["violations"] = nxt.get("violations", 0)  # rotation ~ neutre
        elif kind == "swap":
            nxt["wire_length"] = max(0.0, nxt.get("wire_length", 0.0) * 0.995)

        # correction linéaire apprise sur les features (approx ML du delta)
        f = self.encoder(nxt)
        f_next = self.W @ f + self.b
        nxt["wire_length"] = max(0.0, f_next[3] * 10.0 * max(1, nxt.get("n_nets", 1)))
        nxt["violations"] = max(0, int(round(f_next[4] * 20.0)))
        return nxt

    # ---------------------------------------------------- reward predictor
    def reward_predictor(self, state: Dict) -> float:
        """Récompense prédite : -wl_normalisée - violations * k."""
        f = self.encoder(state)
        wl_norm = float(f[3])
        viol = float(f[4])
        return -(wl_norm + viol * self.violation_weight)

    # -------------------------------------------------------------- learning
    def fit_transition(self, features: np.ndarray, features_next: np.ndarray,
                       lr: float = 1e-3) -> float:
        """Ajuste la dynamique linéaire sur une transition observée (moindres carrés)."""
        target = features_next
        pred = self.W @ features + self.b
        err = target - pred
        grad_W = np.outer(err, features)
        self.W += lr * grad_W
        self.b += lr * err
        return float(np.mean(err ** 2))

    # ---------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        """Sauvegarde les poids en npz."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        np.savez(path, W=self.W, b=self.b)

    def load(self, path: str) -> bool:
        """Charge les poids npz — True si succès."""
        if not os.path.exists(path):
            return False
        try:
            data = np.load(path)
            self.W, self.b = data["W"], data["b"]
            return True
        except (OSError, KeyError, ValueError) as exc:
            log.warning("WorldModel.load(%s) échoué: %s", path, exc)
            return False
