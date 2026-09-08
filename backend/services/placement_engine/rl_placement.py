"""Placement par RL / recuit simulé — actions MOVE/ROTATE discrétisées.

Si un `policy` (interface `select_action(features) -> int`, ex. PolicyNetwork
numpy de ai_engine) est fourni, les actions proviennent de la politique ;
sinon recuit heuristique : attraction vers les centroïdes de nets avec
acceptation Metropolis et température décroissante.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence, Tuple

import numpy as np

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.placement_engine.constraint_placement import find_free_spot
from services.router.topological import (
    classify_component,
    clamp_to_board,
    component_nets,
    net_centroid,
    hpwl_wire_length,
    placement_free,
)

log = get_logger("placement.rl")

# Espace d'actions discrétisé : (dx, dy, drotation_degrés)
ACTIONS: Tuple[Tuple[float, float, float], ...] = (
    (0.0, 0.0, 0.0),      # 0 : noop
    (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
    (2.0, 0.0, 0.0), (-2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, -2.0, 0.0),
    (0.0, 0.0, 90.0),     # 9 : rotation +90°
    (0.0, 0.0, -90.0),    # 10 : rotation −90°
)
FEATURE_DIM = 8


class RLPlacer:
    """Optimise le placement par politique RL ou par recuit simulé (défaut)."""

    def __init__(self, policy=None, seed: int = 0, iterations: int = 30,
                 t0: float = 2.0, cooling: float = 0.85,
                 step_factor: float = 0.6) -> None:
        self.policy = policy
        self.rng = random.Random(seed)
        self.iterations = iterations
        self.t0 = t0
        self.cooling = cooling
        self.step_factor = step_factor

    # ------------------------------------------------------------------ public
    def place(self, graph: DesignGraph) -> DesignGraph:
        """Retourne une COPIE du graphe optimisée (HPWL minimisée)."""
        g = graph.copy()
        movable = [ref for ref, comp in g.components.items()
                   if classify_component(comp) != "mount" and component_nets(g, ref)]
        if not movable:
            return g
        if self.policy is not None:
            self._episode_policy(g, movable)
        else:
            self._annealing(g, movable)
        return g

    # ---------------------------------------------------------------- recuit
    def _annealing(self, g: DesignGraph, movable: Sequence[str]) -> None:
        """30 itérations : chaque composant est attiré vers ses centroïdes de nets,
        acceptation Metropolis exp(−Δ/T), T décroissante géométrique."""
        board_diag = math.hypot(*g.board_size)
        best_score = hpwl_wire_length(g)
        for it in range(self.iterations):
            temperature = self.t0 * (self.cooling ** it)
            centroids = {n.net_id: net_centroid(g, n) for n in g.nets.values()}
            for ref in movable:
                comp = g.get(ref)
                pulls = [c for c in (centroids.get(n.net_id) for n in component_nets(g, ref))
                         if c is not None]
                if not pulls:
                    continue
                px = sum(c.x for c in pulls) / len(pulls) - comp.x
                py = sum(c.y for c in pulls) / len(pulls) - comp.y
                norm = math.hypot(px, py)
                if norm < 1e-9:
                    continue
                step = min(norm, board_diag * 0.05) * self.step_factor
                jitter = temperature * 0.5
                w, h = comp.bbox
                tx = comp.x + px / norm * step + self.rng.uniform(-jitter, jitter)
                ty = comp.y + py / norm * step + self.rng.uniform(-jitter, jitter)
                tx, ty = clamp_to_board(g, tx, ty, w, h, 1.0)
                spot = find_free_spot(g, ref, tx, ty)
                if spot is None:
                    continue
                before = (comp.x, comp.y)
                g.place(ref, spot[0], spot[1], rotation=comp.rotation)
                new_score = hpwl_wire_length(g)
                delta = new_score - best_score
                if delta < 0 or self.rng.random() < math.exp(-delta / max(1e-9, temperature)):
                    best_score = new_score          # accepté
                else:
                    g.place(ref, before[0], before[1], rotation=comp.rotation)
        log.info("recuit placement : %d itérations, HPWL final %.1f mm",
                 self.iterations, best_score)

    # ------------------------------------------------------------- politique
    def _episode_policy(self, g: DesignGraph, movable: Sequence[str]) -> None:
        """Suit la politique : features → action discrète, acceptation gloutonne."""
        board_w, board_h = g.board_size
        board_diag = math.hypot(board_w, board_h)
        best_score = hpwl_wire_length(g)
        steps = min(400, 25 * len(movable))
        for step_i in range(steps):
            ref = movable[step_i % len(movable)]
            comp = g.get(ref)
            features = np.asarray([
                comp.x / board_w, comp.y / board_h,
                comp.bbox[0] / board_w, comp.bbox[1] / board_h,
                min(comp.power_w, 2.0) / 2.0,
                min(len(comp.pads), 32) / 32.0,
                best_score / board_diag,
                step_i / max(1, steps),
            ], dtype=np.float64)
            action_idx = int(self.policy.select_action(features))
            action_idx = max(0, min(action_idx, len(ACTIONS) - 1))
            dx, dy, drot = ACTIONS[action_idx]
            if dx == 0.0 and dy == 0.0 and drot == 0.0:
                continue
            w, h = comp.bbox
            tx, ty = clamp_to_board(g, comp.x + dx, comp.y + dy, w, h, 1.0)
            trot = (comp.rotation + drot) % 360.0
            spot = find_free_spot(g, ref, tx, ty) if (dx or dy) else (tx, ty)
            if spot is None:
                continue
            before = (comp.x, comp.y, comp.rotation)
            g.place(ref, spot[0], spot[1], rotation=trot)
            new_score = hpwl_wire_length(g)
            if new_score <= best_score + 1e-9:
                best_score = new_score              # action conservée
            else:
                g.place(ref, before[0], before[1], rotation=before[2])
        log.info("placement RL : %d pas (politique %s), HPWL %.1f mm",
                 steps, type(self.policy).__name__, best_score)
