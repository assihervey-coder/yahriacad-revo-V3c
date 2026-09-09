"""Placement initial — grille ordonnée 2.54 mm par classes fonctionnelles.

Connecteurs au bord gauche/droit, MCU au centre, composants power au bord
droit, passifs autour du MCU en rangées de grille ; collision keepout ou
chevauchement → décalage en spirale via `find_free_spot`.
"""
from __future__ import annotations

import math

from shared.utilities import get_logger

from services.design_core import DesignGraph
from services.placement_engine.constraint_placement import find_free_spot
from services.router.topological import (
    clamp_to_board,
    classify_component,
    component_nets,
    snap,
)

log = get_logger("placement.initial")

PITCH = 2.54              # grille de placement standard (pouces → mm)
EDGE_MARGIN = 2.0         # recul de bord pour les composants


class InitialPlacer:
    """Placement en grille ordonnée : classes → régions, passifs en rangées."""

    def __init__(self, pitch: float = PITCH, edge_margin: float = EDGE_MARGIN) -> None:
        self.pitch = pitch
        self.edge_margin = edge_margin

    # ------------------------------------------------------------------ public
    def place(self, graph: DesignGraph) -> DesignGraph:
        """Retourne une COPIE du graphe avec tous les composants placés en grille."""
        g = graph.copy()
        bw, bh = g.board_size
        pitch = self.pitch
        placed_groups = self._classify(g)

        # 1) trous de montage → 4 coins
        for i, ref in enumerate(placed_groups["mount"][:4]):
            cx = EDGE_MARGIN + 1.0 if i % 2 == 0 else bw - EDGE_MARGIN - 1.0
            cy = EDGE_MARGIN + 1.0 if i < 2 else bh - EDGE_MARGIN - 1.0
            self._place_free(g, ref, cx, cy)

        # 2) connecteurs → bords gauche (défaut) ou droit (nom explicite)
        left = [r for r in placed_groups["connector"]
                if "right" not in r.lower() and "droite" not in r.lower()]
        right = [r for r in placed_groups["connector"] if r not in left]
        for i, ref in enumerate(left):
            comp = g.get(ref)
            cy = bh * (i + 1) / (len(left) + 1)
            self._place_free(g, ref, self.edge_margin + comp.bbox[0] / 2.0, snap(cy, pitch))
        for i, ref in enumerate(right):
            comp = g.get(ref)
            cy = bh * (i + 1) / (len(right) + 1)
            self._place_free(g, ref, bw - self.edge_margin - comp.bbox[0] / 2.0, snap(cy, pitch))

        # 3) MCU → centre (offsets en quinconce si plusieurs)
        for i, ref in enumerate(placed_groups["mcu"]):
            dx = 0.0 if i == 0 else (pitch * 4 * ((i + 1) // 2) * (1 if i % 2 else -1))
            self._place_free(g, ref, snap(bw / 2 + dx, pitch), snap(bh / 2, pitch))

        # 4) composants power → bord droit (dissipation / proximité condensateurs)
        for i, ref in enumerate(placed_groups["power"]):
            comp = g.get(ref)
            cy = snap(bh * (i + 1) / (len(placed_groups["power"]) + 1), pitch)
            self._place_free(g, ref, bw - self.edge_margin - comp.bbox[0] / 2.0, cy)

        # 5) passifs + autres → remplissage en rangées autour du MCU
        occupied = self._occupied_cells(g, pitch)
        cx0, cy0 = bw / 2.0, bh / 2.0
        for ref in placed_groups["passive"] + placed_groups["other"]:
            spot = self._next_grid_cell(g, occupied, cx0, cy0, pitch)
            if spot is None:
                log.warning("plus de cellule de grille libre pour %s", ref)
                continue
            self._place_free(g, ref, spot[0], spot[1])
        log.info("placement initial : %d composants sur grille %.2f mm (HPWL %.1f mm)",
                 len(g.components), pitch, _hpwl_mm(g))
        return g

    # ----------------------------------------------------------------- internes
    def _classify(self, g: DesignGraph) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {
            "mount": [], "connector": [], "mcu": [], "power": [],
            "passive": [], "other": [],
        }
        for ref, comp in g.components.items():
            kind = classify_component(comp)
            if kind == "mount":
                groups["mount"].append(ref)
            elif kind == "connector":
                groups["connector"].append(ref)
            elif kind == "mcu":
                groups["mcu"].append(ref)
            elif kind == "power":
                groups["power"].append(ref)
            elif kind == "passive":
                groups["passive"].append(ref)
            else:
                groups["other"].append(ref)
        # passifs connectés aux nets du MCU d'abord (priorité de proximité)
        if groups["mcu"]:
            mcu_nets = {n.net_id for n in component_nets(g, groups["mcu"][0])}
            near = [r for r in groups["passive"]
                    if any(pad.net_id in mcu_nets for pad in g.get(r).pads)]
            groups["passive"] = near + [r for r in groups["passive"] if r not in near]
        return groups

    def _place_free(self, g: DesignGraph, ref: str, cx: float, cy: float) -> None:
        """Place sur la grille ; en cas de collision → spirale (find_free_spot)."""
        comp = g.get(ref)
        w, h = comp.bbox
        cx, cy = clamp_to_board(g, cx, cy, w, h, self.edge_margin)
        spot = find_free_spot(g, ref, snap(cx, self.pitch), snap(cy, self.pitch))
        if spot is None:
            spot = find_free_spot(g, ref, cx, cy)
        if spot is None:
            log.warning("aucun emplacement libre trouvé pour %s — placement forcé", ref)
            g.place(ref, cx, cy)
            return
        g.place(ref, spot[0], spot[1])

    def _occupied_cells(self, g: DesignGraph, pitch: float) -> set:
        """Cellules (ix, iy) occupées par les composants déjà placés."""
        cells: set = set()
        for comp in g.components.values():
            if not comp.placed:
                continue
            w, h = comp.bbox
            for ix in range(int((comp.x - w) / pitch), int((comp.x + w) / pitch) + 1):
                for iy in range(int((comp.y - h) / pitch), int((comp.y + h) / pitch) + 1):
                    cells.add((ix, iy))
        return cells

    def _next_grid_cell(self, g: DesignGraph, occupied: set, cx0: float, cy0: float,
                        pitch: float) -> tuple[float, float] | None:
        """Plus proche cellule de grille libre autour du centre (rangées concentriques)."""
        bw, bh = g.board_size
        n_x = int((bw - 2 * self.edge_margin) / pitch)
        n_y = int((bh - 2 * self.edge_margin) / pitch)
        _ix0, _iy0 = int(round(cx0 / pitch)), int(round(cy0 / pitch))
        candidates: list[tuple[float, int, int]] = []
        for ix in range(1, n_x):
            for iy in range(1, n_y):
                if (ix, iy) in occupied:
                    continue
                x, y = ix * pitch, iy * pitch
                if not (self.edge_margin < x < bw - self.edge_margin
                        and self.edge_margin < y < bh - self.edge_margin):
                    continue
                candidates.append((math.hypot(x - cx0, y - cy0), ix, iy))
        candidates.sort()
        for _, ix, iy in candidates:
            if (ix, iy) in occupied:
                continue
            occupied.add((ix, iy))   # réservation optimiste
            return (ix * pitch, iy * pitch)
        return None


def _hpwl_mm(g: DesignGraph) -> float:
    from services.router.topological import hpwl_wire_length
    return hpwl_wire_length(g)
