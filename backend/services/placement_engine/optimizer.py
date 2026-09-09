"""Optimiseur de placement local — déplacements ±{0.5, 1, 2} mm et rotations 90°.

Conserve un mouvement si la longueur filaire estimée (distances centre-à-centre
des pins d'un même net, HPWL étoile) diminue, sans créer de chevauchement.
"""
from __future__ import annotations

from shared.utilities import get_logger

from services.design_core import DesignGraph
from services.router.topological import (
    clamp_to_board,
    classify_component,
    hpwl_wire_length,
    placement_free,
)

log = get_logger("placement.optimizer")

MOVES_MM = ((0.5, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.0, -0.5),
            (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
            (2.0, 0.0), (-2.0, 0.0), (0.0, 2.0), (0.0, -2.0))
ROTATIONS = (90.0, -90.0)


class PlacementOptimizer:
    """Descente locale gloutonne sur la longueur filaire estimée."""

    def __init__(self, min_improvement: float = 1e-6) -> None:
        self.min_improvement = min_improvement

    def optimize(self, graph: DesignGraph, iterations: int = 100) -> tuple:
        """Retourne (copie du graphe optimisée, score final en mm)."""
        g = graph.copy()
        movable = [ref for ref, comp in g.components.items()
                   if comp.placed and classify_component(comp) != "mount"]
        score = hpwl_wire_length(g)
        total_moves = 0
        sweeps = 0
        for _ in range(max(1, iterations)):
            sweeps += 1
            improved = False
            for ref in movable:
                if self._try_improve(g, ref, score):
                    score = hpwl_wire_length(g)
                    improved = True
                    total_moves += 1
            if not improved:
                break
        log.info("optimiseur placement : %d mouvements, HPWL %.1f mm (%d balayages)",
                 total_moves, score, sweeps)
        return g, score

    def _try_improve(self, g: DesignGraph, ref: str, current_score: float) -> bool:
        """Teste tous les mouvements élémentaires d'un composant ; applique le meilleur."""
        comp = g.get(ref)
        w, h = comp.bbox
        candidates: list[tuple[float, float, float]] = []
        for dx, dy in MOVES_MM:
            tx, ty = clamp_to_board(g, comp.x + dx, comp.y + dy, w, h, 0.6)
            candidates.append((tx, ty, comp.rotation))
        for drot in ROTATIONS:
            candidates.append((comp.x, comp.y, (comp.rotation + drot) % 360.0))

        best: tuple[float, float, float, float] | None = None  # (score, x, y, rot)
        for (tx, ty, trot) in candidates:
            before = (comp.x, comp.y, comp.rotation)
            if (abs(tx - before[0]) < 1e-9 and abs(ty - before[1]) < 1e-9
                    and abs(trot - before[2]) < 1e-9):
                continue
            g.place(ref, tx, ty, rotation=trot)
            if placement_free(g, ref, tx, ty):
                s = hpwl_wire_length(g)
                if s < current_score - self.min_improvement and (best is None or s < best[0]):
                    best = (s, tx, ty, trot)
            g.place(ref, before[0], before[1], rotation=before[2])
        if best is None:
            return False
        g.place(ref, best[1], best[2], rotation=best[3])
        return True
