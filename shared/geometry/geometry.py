"""Géométrie 2D partagée — points, segments, polygones, chemins de routage.

Utilisée par design_core (design_graph), router, placement_engine,
verification (DRC) et exporter (Gerber). Basée sur shapely si disponible,
implémentation numpy sinon.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

Point2 = tuple[float, float]  # (x_mm, y_mm)


@dataclass(frozen=True)
class Point:
    """Point 2D en millimètres (format interne unique de la plateforme)."""

    x: float
    y: float

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def translated(self, dx: float, dy: float) -> Point:
        return Point(self.x + dx, self.y + dy)

    def rotated(self, angle_deg: float, origin: Point | None = None) -> Point:
        o = origin or Point(0.0, 0.0)
        a = math.radians(angle_deg)
        dx, dy = self.x - o.x, self.y - o.y
        return Point(o.x + dx * math.cos(a) - dy * math.sin(a),
                     o.y + dx * math.sin(a) + dy * math.cos(a))

    def to_tuple(self) -> Point2:
        return (self.x, self.y)

    @classmethod
    def from_tuple(cls, t: Sequence[float]) -> Point:
        return cls(float(t[0]), float(t[1]))


@dataclass
class Segment:
    start: Point
    end: Point
    layer: int = 0
    width_mm: float = 0.2

    def length(self) -> float:
        return self.start.distance_to(self.end)

    def distance_point_to_segment(self, p: Point) -> float:
        """Distance point → segment (pour le DRC clearance)."""
        ax, ay = self.start.x, self.start.y
        bx, by = self.end.x, self.end.y
        px, py = p.x, p.y
        dx, dy = bx - ax, by - ay
        len2 = dx * dx + dy * dy
        if len2 == 0.0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


@dataclass
class Polygon:
    """Polygone (empreinte, keepout, plan de masse). Sens horaire ou anti-horaire."""

    points: list[Point]
    layer: int = 0

    def area(self) -> float:
        n = len(self.points)
        if n < 3:
            return 0.0
        s = 0.0
        for i in range(n):
            x1, y1 = self.points[i].to_tuple()
            x2, y2 = self.points[(i + 1) % n].to_tuple()
            s += x1 * y2 - x2 * y1
        return abs(s) / 2.0

    def bbox(self) -> tuple[Point, Point]:
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        return Point(min(xs), min(ys)), Point(max(xs), max(ys))

    def contains(self, p: Point) -> bool:
        """Ray casting."""
        inside = False
        n = len(self.points)
        j = n - 1
        for i in range(n):
            xi, yi = self.points[i].to_tuple()
            xj, yj = self.points[j].to_tuple()
            if ((yi > p.y) != (yj > p.y)) and (
                p.x < (xj - xi) * (p.y - yi) / (yj - yi) + xi
            ):
                inside = not inside
            j = i
        return inside


@dataclass
class RoutePath:
    """Chemin de routage : suite de points sur une couche, avec largeur et vias."""

    net_id: str
    points: list[Point] = field(default_factory=list)
    layer: int = 0
    width_mm: float = 0.2
    vias: list[tuple[Point, int, int]] = field(default_factory=list)  # (pos, from_layer, to_layer)

    def length(self) -> float:
        if len(self.points) < 2:
            return 0.0
        return sum(
            self.points[i].distance_to(self.points[i + 1])
            for i in range(len(self.points) - 1)
        )

    def segments(self) -> Iterable[Segment]:
        for i in range(len(self.points) - 1):
            yield Segment(self.points[i], self.points[i + 1], self.layer, self.width_mm)


@dataclass
class BBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @classmethod
    def from_center(cls, cx: float, cy: float, w: float, h: float) -> BBox:
        return cls(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> Point:
        return Point((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)

    def overlaps(self, other: BBox, margin: float = 0.0) -> bool:
        return not (
            self.max_x + margin < other.min_x
            or self.min_x - margin > other.max_x
            or self.max_y + margin < other.min_y
            or self.min_y - margin > other.max_y
        )

    def expand(self, margin: float) -> BBox:
        return BBox(self.min_x - margin, self.min_y - margin,
                    self.max_x + margin, self.max_y + margin)
