"""Placement sous contraintes — power au bord, caps de découplage collés au MCU,
groupes appariés alignés, résolution dure des chevauchements (spirale).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.router.topological import (
    classify_component,
    clamp_to_board,
    component_nets,
    pad_position,
    placement_free,
)

log = get_logger("placement.constraint")

DECAP_GAP_MM = 3.0        # distance max condensateur de découplage ↔ pin MCU
EDGE_MARGIN_MM = 3.0      # recul des composants power pour dissipation en bord


def find_free_spot(graph: DesignGraph, ref: str, cx: float, cy: float,
                   max_tries: int = 400) -> Optional[Tuple[float, float]]:
    """Premier emplacement libre autour de (cx, cy) — spirale archimédienne.

    Pas de 0.4 mm, angle d'or (2.399 rad) pour un balayage uniforme ; teste
    bord de carte, keepouts et chevauchements via `placement_free`.
    """
    if placement_free(graph, ref, cx, cy):
        return (cx, cy)
    for k in range(1, max_tries):
        r = 0.4 * k ** 0.9
        theta = k * 2.399963229728653
        x, y = cx + r * math.cos(theta), cy + r * math.sin(theta)
        x, y = round(x, 3), round(y, 3)
        if placement_free(graph, ref, x, y):
            return (x, y)
    return None


def resolve_overlaps(graph: DesignGraph) -> int:
    """Résolution DURE des chevauchements : le plus petit composant est déplacé
    en spirale. Retourne le nombre de composants déplacés."""
    moved = 0
    comps = [c for c in graph.components.values() if c.placed]
    comps.sort(key=lambda c: c.bbox[0] * c.bbox[1])  # petits d'abord
    for comp in comps:
        if _first_overlap(graph, comp.ref) is None:
            continue
        spot = find_free_spot(graph, comp.ref, comp.x, comp.y)
        if spot is not None:
            graph.place(comp.ref, spot[0], spot[1], rotation=comp.rotation)
            moved += 1
    return moved


def _first_overlap(graph: DesignGraph, ref: str) -> Optional[str]:
    comp = graph.get(ref)
    w, h = comp.bbox
    for other_ref, other in graph.components.items():
        if other_ref == ref or not other.placed:
            continue
        if (other.side or "top") != (comp.side or "top"):
            continue
        ow, oh = other.bbox
        if not (comp.x + w / 2 <= other.x - ow / 2 or comp.x - w / 2 >= other.x + ow / 2
                or comp.y + h / 2 <= other.y - oh / 2 or comp.y - h / 2 >= other.y + oh / 2):
            return other_ref
    return None


class ConstraintPlacer:
    """Applique les règles de contraintes de placement (power, découplage, appariés)."""

    def __init__(self, decap_gap_mm: float = DECAP_GAP_MM,
                 edge_margin_mm: float = EDGE_MARGIN_MM) -> None:
        self.decap_gap_mm = decap_gap_mm
        self.edge_margin_mm = edge_margin_mm

    def place(self, graph: DesignGraph,
              constraints: Optional[Dict] = None) -> DesignGraph:
        """Retourne une COPIE du graphe avec les contraintes appliquées."""
        g = graph.copy()
        n_power = self._power_near_edges(g)
        n_decap = self._decoupling_caps(g)
        n_align = self._align_matched_groups(g)
        moved = resolve_overlaps(g)
        log.info("contraintes : %d power au bord, %d caps collés, %d groupes alignés, "
                 "%d chevauchements résolus", n_power, n_decap, n_align, moved)
        return g

    # ----------------------------------------------------------------- règles
    def _power_near_edges(self, g: DesignGraph) -> int:
        """Composants power (power_w>0.5 ou régulateur) plaqués au bord le plus proche."""
        moved = 0
        bw, bh = g.board_size
        for ref, comp in list(g.components.items()):
            kind = classify_component(comp)
            if kind != "power":
                continue
            w, h = comp.bbox
            edges = [
                (self.edge_margin_mm + w / 2, comp.y),          # gauche
                (bw - self.edge_margin_mm - w / 2, comp.y),     # droite
                (comp.x, self.edge_margin_mm + h / 2),          # bas
                (comp.x, bh - self.edge_margin_mm - h / 2),     # haut
            ]
            edges.sort(key=lambda p: math.hypot(p[0] - comp.x, p[1] - comp.y))
            for ex, ey in edges:
                ex, ey = clamp_to_board(g, ex, ey, w, h, self.edge_margin_mm)
                spot = find_free_spot(g, ref, ex, ey)
                if spot is not None:
                    g.place(ref, spot[0], spot[1], rotation=comp.rotation)
                    moved += 1
                    break
        return moved

    def _decoupling_caps(self, g: DesignGraph) -> int:
        """Condensateurs de découplage collés (<3 mm) au pin MCU de leur net."""
        moved = 0
        for ref, comp in list(g.components.items()):
            if not ref.upper().startswith("C") or len(comp.pads) < 2:
                continue
            for net in component_nets(g, ref):
                # trouve un composant IC (U*) sur ce net avec un pad positionné
                anchor = None
                for pin_ref, pad_name in net.pins:
                    if pin_ref not in g.components or pin_ref == ref:
                        continue
                    if not pin_ref.upper().startswith("U"):
                        continue
                    ucomp = g.get(pin_ref)
                    upad = next((p for p in ucomp.pads if p.name == pad_name), None)
                    if upad is not None:
                        anchor = (pin_ref, pad_position(g, pin_ref, pad_name), ucomp)
                        break
                if anchor is None:
                    continue
                pin_ref, pin_pos, ucomp = anchor
                dx, dy = comp.x - ucomp.x, comp.y - ucomp.y
                norm = math.hypot(dx, dy) or 1.0
                w, h = comp.bbox
                target = (pin_pos.x + dx / norm * 1.5, pin_pos.y + dy / norm * 1.5)
                target = clamp_to_board(g, target[0], target[1], w, h, 1.0)
                spot = find_free_spot(g, ref, target[0], target[1])
                if spot is not None and math.hypot(
                        spot[0] - pin_pos.x, spot[1] - pin_pos.y) <= self.decap_gap_mm + w / 2:
                    g.place(ref, spot[0], spot[1], rotation=comp.rotation)
                    moved += 1
                break   # un seul placement de découplage par condensateur
        return moved

    def _align_matched_groups(self, g: DesignGraph) -> int:
        """Composants d'un même matched_group alignés (même Y, ordre X conservé)."""
        groups: Dict[str, List[str]] = {}
        for net in g.nets.values():
            if not net.matched_group:
                continue
            for pin_ref, _ in net.pins:
                if pin_ref in g.components and pin_ref not in groups.get(net.matched_group, []):
                    groups.setdefault(net.matched_group, []).append(pin_ref)
        moved = 0
        for group, refs in groups.items():
            if len(refs) < 2:
                continue
            mean_y = sum(g.get(r).y for r in refs) / len(refs)
            rot = sorted(g.get(r).rotation for r in refs)[len(refs) // 2]  # rotation médiane
            for ref in refs:
                comp = g.get(ref)
                spot = find_free_spot(g, ref, comp.x, mean_y)
                if spot is not None:
                    g.place(ref, spot[0], spot[1], rotation=rot)
                    moved += 1
        return moved
