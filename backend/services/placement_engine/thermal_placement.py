"""Placement thermique — espacement des sources de chaleur, régulateurs en bord,
hotspots éloignés des cristaux et capteurs sensibles.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from shared.utilities import get_logger

from services.design_core import Component, DesignGraph

from services.placement_engine.constraint_placement import find_free_spot, resolve_overlaps
from services.router.topological import classify_component, clamp_to_board

log = get_logger("placement.thermal")

MIN_POWER_GAP_MM = 8.0        # distance min entre sources de chaleur > 0.5 W
HOTSPOT_CLEARANCE_MM = 10.0   # distance min hotspot ↔ cristal/capteur
SENSOR_HINTS = ("sensor", "tmp", "imu", "humid", "press", "accel", "gyro")


def _is_hot(comp: Component) -> bool:
    return comp.power_w > 0.5 or classify_component(comp) == "power"


def _is_sensitive(comp: Component) -> bool:
    text = f"{comp.ref} {getattr(comp, 'value', '')} {getattr(comp, 'footprint', '')}".lower()
    return classify_component(comp) == "crystal" or any(h in text for h in SENSOR_HINTS)


class ThermalPlacer:
    """Éloigne les sources de chaleur entre elles et des organes sensibles."""

    def __init__(self, min_power_gap_mm: float = MIN_POWER_GAP_MM,
                 hotspot_clearance_mm: float = HOTSPOT_CLEARANCE_MM) -> None:
        self.min_power_gap_mm = min_power_gap_mm
        self.hotspot_clearance_mm = hotspot_clearance_mm

    def place(self, graph: DesignGraph,
              constraints: Optional[Dict] = None) -> DesignGraph:
        """Retourne une COPIE du graphe avec les règles thermiques appliquées."""
        g = graph.copy()
        n_edge = self._regulators_to_edges(g)
        n_spread = self._spread_hot_components(g)
        n_clear = self._clear_sensitive_zones(g)
        resolve_overlaps(g)
        log.info("thermique : %d régulateurs au bord, %d paires écartées (≥%.0f mm), "
                 "%d zones sensibles dégagées (≥%.0f mm)",
                 n_edge, n_spread, self.min_power_gap_mm, n_clear,
                 self.hotspot_clearance_mm)
        return g

    # ----------------------------------------------------------------- règles
    def _regulators_to_edges(self, g: DesignGraph) -> int:
        """Régulateurs / VRM plaqués au bord le plus proche (dissipation cuivre)."""
        bw, bh = g.board_size
        moved = 0
        for ref, comp in list(g.components.items()):
            if comp.power_w <= 0.2:
                continue
            kind = classify_component(comp)
            if kind != "power":
                continue
            w, h = comp.bbox
            edges = [
                (w / 2 + 2.0, comp.y), (bw - w / 2 - 2.0, comp.y),
                (comp.x, h / 2 + 2.0), (comp.x, bh - h / 2 - 2.0),
            ]
            edges.sort(key=lambda p: math.hypot(p[0] - comp.x, p[1] - comp.y))
            for ex, ey in edges:
                ex, ey = clamp_to_board(g, ex, ey, w, h, 1.0)
                spot = find_free_spot(g, ref, ex, ey)
                if spot is not None:
                    g.place(ref, spot[0], spot[1], rotation=comp.rotation)
                    moved += 1
                    break
        return moved

    def _spread_hot_components(self, g: DesignGraph) -> int:
        """Écarte les composants power (power_w > 0.5) d'au moins min_power_gap_mm."""
        hots = [c for c in g.components.values() if c.placed and _is_hot(c)]
        moved = 0
        for _ in range(20):                       # relaxation itérative
            worst: Optional[Tuple[str, str, float, float, float]] = None
            for i in range(len(hots)):
                for j in range(i + 1, len(hots)):
                    a, b = hots[i], hots[j]
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    if d < self.min_power_gap_mm and (worst is None or d < worst[2]):
                        dx, dy = b.x - a.x, b.y - a.y
                        worst = (a.ref, b.ref, d, dx, dy)
            if worst is None:
                break
            ref_a, ref_b, d, dx, dy = worst
            norm = math.hypot(dx, dy) or 1.0
            push = (self.min_power_gap_mm - d) / 2.0
            moved += self._push(g, ref_a, -dx / norm * push, -dy / norm * push)
            moved += self._push(g, ref_b, dx / norm * push, dy / norm * push)
        return moved

    def _clear_sensitive_zones(self, g: DesignGraph) -> int:
        """Éloigne cristaux/capteurs des hotspots (hotspot_clearance_mm)."""
        hots = [c for c in g.components.values() if c.placed and _is_hot(c)]
        sens = [c for c in g.components.values() if c.placed and _is_sensitive(c)]
        moved = 0
        for s in sens:
            for h in hots:
                d = math.hypot(s.x - h.x, s.y - h.y)
                if d >= self.hotspot_clearance_mm:
                    continue
                dx, dy = (s.x - h.x) or 0.7, (s.y - h.y) or 0.7
                norm = math.hypot(dx, dy)
                target_d = self.hotspot_clearance_mm + s.bbox[0] / 2.0
                tx, ty = h.x + dx / norm * target_d, h.y + dy / norm * target_d
                w, hh = s.bbox
                tx, ty = clamp_to_board(g, tx, ty, w, hh, 1.0)
                spot = find_free_spot(g, s.ref, tx, ty)
                if spot is not None:
                    g.place(s.ref, spot[0], spot[1], rotation=s.rotation)
                    moved += 1
                break
        return moved

    def _push(self, g: DesignGraph, ref: str, dx: float, dy: float) -> int:
        comp = g.get(ref)
        w, h = comp.bbox
        tx, ty = clamp_to_board(g, comp.x + dx, comp.y + dy, w, h, 1.0)
        spot = find_free_spot(g, ref, tx, ty)
        if spot is None:
            return 0
        g.place(ref, spot[0], spot[1], rotation=comp.rotation)
        return 1
