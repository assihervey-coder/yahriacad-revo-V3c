"""Tests unitaires — géométrie 2D partagée (shared.geometry).

Point (distance/rotation), Polygon (aire/contains), RoutePath (longueur),
BBox (overlaps). Toutes les valeurs en millimètres (format interne).
"""
from __future__ import annotations

import pytest

from shared.geometry import BBox, Point, Polygon, RoutePath


# ------------------------------------------------------------------ Point ----
class TestPoint:
    def test_distance_classique_3_4_5(self) -> None:
        assert Point(0.0, 0.0).distance_to(Point(3.0, 4.0)) == pytest.approx(5.0)

    def test_distance_zero(self) -> None:
        assert Point(1.5, -2.0).distance_to(Point(1.5, -2.0)) == 0.0

    def test_rotation_90deg(self) -> None:
        p = Point(1.0, 0.0).rotated(90.0)
        assert p.x == pytest.approx(0.0, abs=1e-9)
        assert p.y == pytest.approx(1.0, abs=1e-9)

    def test_rotation_360deg_identite(self) -> None:
        p = Point(7.3, -4.2).rotated(360.0)
        assert p.x == pytest.approx(7.3, abs=1e-9)
        assert p.y == pytest.approx(-4.2, abs=1e-9)

    def test_rotation_autour_d_un_origine(self) -> None:
        # (2, 2) tourné de 180° autour de (1, 1) → (0, 0)
        p = Point(2.0, 2.0).rotated(180.0, origin=Point(1.0, 1.0))
        assert p.x == pytest.approx(0.0, abs=1e-9)
        assert p.y == pytest.approx(0.0, abs=1e-9)

    def test_tuple_round_trip(self) -> None:
        assert Point.from_tuple((3.0, 4.0)).to_tuple() == (3.0, 4.0)


# ---------------------------------------------------------------- Polygon ----
class TestPolygon:
    def test_aire_rectangle(self) -> None:
        rect = Polygon([Point(0, 0), Point(3, 0), Point(3, 4), Point(0, 4)])
        assert rect.area() == pytest.approx(12.0)

    def test_aire_triangle(self) -> None:
        tri = Polygon([Point(0, 0), Point(4, 0), Point(0, 3)])
        assert tri.area() == pytest.approx(6.0)

    def test_aire_degenerate(self) -> None:
        assert Polygon([Point(0, 0), Point(1, 1)]).area() == 0.0

    def test_contains_interieur_exterieur(self) -> None:
        rect = Polygon([Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)])
        assert rect.contains(Point(5, 5)) is True
        assert rect.contains(Point(15, 5)) is False
        assert rect.contains(Point(-1, 5)) is False

    def test_bbox_englobante(self) -> None:
        tri = Polygon([Point(0, 0), Point(4, 0), Point(0, 3)])
        (mn, mx) = tri.bbox()
        assert (mn.x, mn.y, mx.x, mx.y) == (0.0, 0.0, 4.0, 3.0)


# --------------------------------------------------------------- RoutePath ----
class TestRoutePath:
    def test_longueur_chemin_en_L(self) -> None:
        path = RoutePath(net_id="N1", points=[Point(0, 0), Point(3, 0), Point(3, 4)])
        assert path.length() == pytest.approx(7.0)

    def test_longueur_point_unique(self) -> None:
        assert RoutePath(net_id="N1", points=[Point(2, 2)]).length() == 0.0

    def test_segments_un_par_paire(self) -> None:
        path = RoutePath(net_id="N1", points=[Point(0, 0), Point(1, 0), Point(1, 1)])
        assert len(list(path.segments())) == 2


# ------------------------------------------------------------------- BBox ----
class TestBBox:
    def test_from_center(self) -> None:
        bbox = BBox.from_center(0.0, 0.0, 4.0, 2.0)
        assert (bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y) == (-2.0, -1.0, 2.0, 1.0)
        assert bbox.width == pytest.approx(4.0)
        assert bbox.height == pytest.approx(2.0)
        assert bbox.center == Point(0.0, 0.0)

    def test_overlaps_et_marge(self) -> None:
        a = BBox(0, 0, 2, 2)
        b = BBox(2, 0, 4, 2)          # bord partagé
        assert a.overlaps(b) is True
        c = BBox(2.05, 0, 4, 2)       # séparé de 0.05 mm
        assert a.overlaps(c) is False
        assert a.overlaps(c, margin=0.1) is True   # la marge élargit la zone effective

    def test_overlaps_distincts(self) -> None:
        a = BBox(0, 0, 2, 2)
        assert a.overlaps(BBox(1, 1, 3, 3)) is True
        assert a.overlaps(BBox(10, 10, 12, 12)) is False

    def test_expand(self) -> None:
        expanded = BBox(0, 0, 2, 2).expand(0.5)
        assert (expanded.min_x, expanded.max_y) == (-0.5, 2.5)
