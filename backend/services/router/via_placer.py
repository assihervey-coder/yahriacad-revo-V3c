"""Placement des vias — jonctions de changement de couche et coût parasité.

Le coût d'un via est estimé par la formule classique de capacité de baril
C = 1.41·εr·T·D1/(D2−D1) [pF] (T, D1, D2 en pouces) ≈ 0.3–0.5 pF en pratique.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

log = get_logger("router.via_placer")

VIA_DRILL_MM = 0.3      # foret par défaut de la plateforme
VIA_PAD_MM = 0.6        # plot annulaire extérieur
VIA_CLEARANCE_DIA_MM = 1.0  # diamètre d'antipad (clearance plan)

PathLike = RoutePath | tuple[Sequence[Point], int]


@dataclass(frozen=True)
class ViaPlan:
    """Un via planifié : position et transition de couches."""

    pos: Point
    from_layer: int
    to_layer: int

    def as_tuple(self) -> tuple[Point, int, int]:
        return (self.pos, self.from_layer, self.to_layer)


def estimate_via_cost_pf(er: float = 4.3, board_thickness_mm: float = 1.6,
                         pad_dia_mm: float = VIA_PAD_MM,
                         clearance_dia_mm: float = VIA_CLEARANCE_DIA_MM) -> float:
    """Capacité parasite d'un via (pF) — formule 1.41·εr·T·D1/(D2−D1)."""
    t_in = board_thickness_mm / 25.4
    d1_in = pad_dia_mm / 25.4
    d2_in = clearance_dia_mm / 25.4
    denom = max(d2_in - d1_in, 1e-4)
    return 1.41 * er * t_in * d1_in / denom


def estimate_via_cost_mm(via_penalty_mm: float = 3.0) -> float:
    """Coût équivalent en longueur de piste (pour les décisions de routage)."""
    return via_penalty_mm


def _endpoint(path: PathLike, last: bool) -> tuple[Point, int] | None:
    """(point extrême, couche) d'un chemin, None si vide."""
    if isinstance(path, RoutePath):
        if not path.points:
            return None
        layer = path.layer
        pt = path.points[-1] if last else path.points[0]
        return pt, layer
    points, layer = path
    if not points:
        return None
    return (points[-1] if last else points[0]), layer


def plan_vias(path_a: PathLike, path_b: PathLike,
              layers: Sequence[int] | None = None) -> list[tuple[Point, int, int]]:
    """Vias nécessaires aux jonctions entre deux chemins consécutifs.

    Si les couches diffèrent au point de jonction partagé, un via (Point,
    couche_a → couche_b) est produit. `layers` (optionnel) liste l'ordre de
    préférence des couches valides : un via n'est émis que si les deux couches
    de la jonction y figurent.
    """
    end_a = _endpoint(path_a, last=True)
    start_b = _endpoint(path_b, last=False)
    if end_a is None or start_b is None:
        return []
    (pa, la), (pb, lb) = end_a, start_b
    if la == lb:
        return []
    if pa.distance_to(pb) > 0.05:      # jonction discontinue : via au bout de A
        pass
    if layers is not None and (la not in layers or lb not in layers):
        return []
    log.debug("via planifié en (%.2f, %.2f) : L%d → L%d", pa.x, pa.y, la, lb)
    return [(pa, la, lb)]


def plan_vias_for_chunks(chunks: Sequence[tuple[Sequence[Point], int]]) -> list[tuple[Point, int, int]]:
    """Vias le long d'une suite de tronçons (points, couche) partageant leurs extrémités."""
    vias: list[tuple[Point, int, int]] = []
    for i in range(len(chunks) - 1):
        vias.extend(plan_vias(chunks[i], chunks[i + 1]))
    return vias
