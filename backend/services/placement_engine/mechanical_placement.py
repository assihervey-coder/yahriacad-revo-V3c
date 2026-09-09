"""Placement mécanique — connecteurs et trous de montage verrouillés aux bords,
USB-C centré au bord bas, LED d'indication au bord, zones d'assemblage respectées.
"""
from __future__ import annotations

from shared.utilities import get_logger

from services.design_core import DesignGraph
from services.placement_engine.constraint_placement import find_free_spot
from services.router.topological import (
    clamp_to_board,
    classify_component,
    snap,
)

log = get_logger("placement.mechanical")

EDGE_MM = 2.5             # recul standard depuis le bord de carte


class MechanicalPlacer:
    """Verrouillage des composants mécaniques (connecteurs, trous, USB, LEDs)."""

    def __init__(self, edge_mm: float = EDGE_MM) -> None:
        self.edge_mm = edge_mm

    def place(self, graph: DesignGraph,
              constraints: dict | None = None) -> DesignGraph:
        """Retourne une COPIE du graphe avec les contraintes mécaniques appliquées."""
        g = graph.copy()
        bw, bh = g.board_size
        n = {"mount": 0, "usb": 0, "connector": 0, "led": 0}

        # 1) trous de montage → coins (insets = demi-empreinte + 1 mm)
        mounts = [r for r, c in g.components.items()
                  if classify_component(c) == "mount"]
        [(1.0 + 1.0, 1.0 + 1.0), (bw - 4.0, 2.0),
                   (2.0, bh - 4.0), (bw - 4.0, bh - 4.0)]
        for i, ref in enumerate(mounts[:4]):
            comp = g.get(ref)
            inset = max(comp.bbox) / 2.0 + 1.0
            cx = inset if i % 2 == 0 else bw - inset
            cy = inset if i < 2 else bh - inset
            self._lock(g, ref, cx, cy)
            n["mount"] += 1

        # 2) USB-C (ou USB-A/micro) → bord bas, centré
        usb = [r for r, c in g.components.items()
               if "usb" in f"{r} {getattr(c, 'value', '')} {getattr(c, 'footprint', '')}".lower()]
        for ref in usb:
            comp = g.get(ref)
            self._lock(g, ref, bw / 2.0, bh - self.edge_mm - comp.bbox[1] / 2.0)
            n["usb"] += 1

        # 3) connecteurs → bord gauche (droit si le nom l'indique), empilés
        connectors = [r for r, c in g.components.items()
                      if classify_component(c) == "connector" and r not in usb]
        left = [r for r in connectors if "right" not in r.lower()]
        right = [r for r in connectors if r not in left]
        for i, ref in enumerate(left):
            comp = g.get(ref)
            y = snap(bh * (i + 1) / (len(left) + 1), 1.27)
            self._lock(g, ref, self.edge_mm + comp.bbox[0] / 2.0, y)
            n["connector"] += 1
        for i, ref in enumerate(right):
            comp = g.get(ref)
            y = snap(bh * (i + 1) / (len(right) + 1), 1.27)
            self._lock(g, ref, bw - self.edge_mm - comp.bbox[0] / 2.0, y)
            n["connector"] += 1

        # 4) LEDs d'indication → bord haut, réparties
        leds = [r for r, c in g.components.items() if classify_component(c) == "led"]
        for i, ref in enumerate(leds):
            comp = g.get(ref)
            x = bw * (i + 1) / (len(leds) + 1)
            self._lock(g, ref, x, self.edge_mm + comp.bbox[1] / 2.0)
            n["led"] += 1

        log.info("mécanique : %s verrouillés aux bords", n)
        return g

    def _lock(self, g: DesignGraph, ref: str, cx: float, cy: float) -> None:
        """Place un composant mécanique ; keepout/overlap → spirale de décalage."""
        comp = g.get(ref)
        w, h = comp.bbox
        cx, cy = clamp_to_board(g, cx, cy, w, h, 1.0)
        spot = find_free_spot(g, ref, cx, cy)
        if spot is None:
            log.warning("emplacement mécanique impossible pour %s — forcé", ref)
            g.place(ref, cx, cy)
            return
        g.place(ref, spot[0], spot[1], rotation=comp.rotation)
