"""Keepouts et helpers géométriques du design graph (bboxes composants)."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from shared.geometry import Point, Polygon

from services.design_core.design_graph.components import Component

BBoxTuple = tuple[float, float, float, float]   # (min_x, min_y, max_x, max_y)


@dataclass
class Keepout:
    """Zone interdite (polygonale). layer=-1 => toutes les couches."""

    name: str
    polygon: Polygon
    layer: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": [[p.x, p.y] for p in self.polygon.points],
            "layer": self.layer,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Keepout:
        return cls(
            name=str(d.get("name", "keepout")),
            polygon=Polygon(points=[Point.from_tuple(p) for p in d.get("points", [])],
                            layer=int(d.get("layer", -1) or -1)),
            layer=int(d.get("layer", -1) or -1),
        )


def component_bbox_mm(c: Component) -> BBoxTuple:
    """BBox monde d'un composant : (x±w/2, y±h/2) -> (min_x, min_y, max_x, max_y) mm."""
    w, h = c.bbox
    return (c.x - w / 2.0, c.y - h / 2.0, c.x + w / 2.0, c.y + h / 2.0)


def bbox_gap_mm(a: BBoxTuple, b: BBoxTuple) -> float:
    """Écart minimal entre deux bboxes alignées aux axes (0.0 si chevauchement)."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return math.hypot(dx, dy)


def corners_of(x: float, y: float, w: float, h: float) -> list[Point]:
    """Les 4 coins d'une bbox centrée en (x, y) — pour les tests keepout."""
    return [
        Point(x - w / 2.0, y - h / 2.0),
        Point(x + w / 2.0, y - h / 2.0),
        Point(x + w / 2.0, y + h / 2.0),
        Point(x - w / 2.0, y + h / 2.0),
    ]


def bbox_area(b: BBoxTuple) -> float:
    """Aire d'une bbox (mm²)."""
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def make_polygon(points: Sequence[Sequence[float]], layer: int = 0) -> Polygon:
    """Construit un Polygon shared à partir d'une séquence de (x, y)."""
    return Polygon(points=[Point.from_tuple(p) for p in points], layer=layer)
