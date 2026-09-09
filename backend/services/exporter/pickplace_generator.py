"""Générateur Pick&Place (POS) — CSV Ref,Designator,Mid X,Mid Y,Layer,Rotation.

Positions en mm (centre du composant). Pour le côté bottom, la rotation est
corrigée : rot_bottom = (180 - rot) % 360.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from shared.utilities import get_logger

log = get_logger(__name__)

COLUMNS = ["Ref", "Designator", "Mid X", "Mid Y", "Layer", "Rotation"]


class PickPlaceGenerator:
    """Fichier de placement pour machines d'assemblage."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph

    def generate_csv(self, side: str = "top") -> str:
        """CSV des composants d'un côté ('top' ou 'bottom')."""
        side = "bottom" if side.lower().startswith("b") else "top"
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        rows: list[dict] = []
        for ref in sorted(self.graph.components):
            comp = self.graph.components[ref]
            comp_side = str(getattr(comp, "side", "top") or "top").lower()
            if comp_side != side:
                continue
            rot = float(getattr(comp, "rotation", 0.0) or 0.0)
            if side == "bottom":
                rot = (180.0 - rot) % 360.0
            rows.append({
                "Ref": ref,
                "Designator": ref,
                "Mid X": f"{float(comp.x):.4f}",
                "Mid Y": f"{float(comp.y):.4f}",
                "Layer": side,
                "Rotation": f"{rot:.1f}",
            })
        writer.writerows(rows)
        log.info("pick&place %s: %d composants", side, len(rows))
        return buf.getvalue()
