"""Hautes vitesses — mesure des longueurs et serpentins (zigzag) d'égalisation.

`length_match` aligne les longueurs des nets d'un matched_group sur la plus
longue (ou sur max_length_mm), en insérant un peigne orthogonal sur le segment
le plus long du chemin le plus court.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple, Union

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

log = get_logger("router.high_speed")

MATCH_TOL_MM = 0.5          # tolérance d'appariement standard
MAX_AMPLITUDE_MM = 1.5      # amplitude max d'un peigne
MIN_TOOTH_MM = 0.4          # dent minimale (fabricable)


def polyline_length(points: Sequence[Point]) -> float:
    """Longueur totale d'une polyligne (mm)."""
    return sum(points[i].distance_to(points[i + 1]) for i in range(len(points) - 1))


def _unit_perp(a: Point, b: Point) -> Tuple[Point, Point, float]:
    """Direction unitaire et perpendiculaire (à gauche) du segment a→b."""
    dx, dy = b.x - a.x, b.y - a.y
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return Point(1.0, 0.0), Point(0.0, 1.0), 0.0
    return Point(dx / d, dy / d), Point(-dy / d, dx / d), d


def zigzag_points(start: Point, end: Point, extra_mm: float,
                  preferred_amplitude_mm: float = 0.3) -> Optional[List[Point]]:
    """Peigne orthogonal entre start et end ajoutant exactement `extra_mm`.

    Construction : n dents carrées ; chaque dent ajoute 4·a de longueur verticale
    tout en conservant l'avancée horizontale totale d = |end − start|.
    Retourne None si le segment est trop court pour accueillir un peigne.
    """
    u, v, d = _unit_perp(start, end)
    if d < 1.5 or extra_mm <= 0.0:
        return None
    # n dents : extra = 4·n·a ; dents tenant sur le segment : n ≤ d / MIN_TOOTH
    n = max(1, int(math.ceil(extra_mm / (4.0 * preferred_amplitude_mm))))
    n = min(n, max(1, int(d / MIN_TOOTH_MM)))
    amplitude = extra_mm / (4.0 * n)
    if amplitude > MAX_AMPLITUDE_MM:
        amplitude = MAX_AMPLITUDE_MM      # léger déficit → tolérance 0.5 mm
    tooth = d / n

    local: List[Tuple[float, float]] = [(0.0, 0.0)]
    x = y = 0.0
    for i in range(n):
        y = amplitude if i % 2 == 0 else -amplitude
        local.append((x, y))              # transition verticale
        x += tooth / 2.0
        local.append((x, y))              # avance horizontale
        y = -y
        local.append((x, y))              # redescend (2·a)
        x += tooth / 2.0
        local.append((x, y))              # avance horizontale
    local.append((x, 0.0))                # retour à l'axe (a final)
    if abs(x - d) > 1e-6:
        return None
    return [
        Point(start.x + u.x * lx + v.x * ly, start.y + u.y * lx + v.y * ly)
        for lx, ly in local
    ]


def add_serpentine(points: List[Point], extra_mm: float) -> Optional[List[Point]]:
    """Insère un peigne sur le plus long segment de la polyligne (+extra_mm exact)."""
    if len(points) < 2 or extra_mm <= 0.0:
        return None
    lengths = [(points[i].distance_to(points[i + 1]), i)
               for i in range(len(points) - 1)]
    for d, i in sorted(lengths, reverse=True):
        zig = zigzag_points(points[i], points[i + 1], extra_mm)
        if zig is not None:
            return list(points[:i]) + zig + list(points[i + 2:])
    return None


def _resolve_group(graph: DesignGraph, group: Union[str, Sequence[Net]]) -> List[Net]:
    """Nets du groupe : soit une liste de Net, soit un nom de matched_group."""
    if isinstance(group, str):
        return [n for n in graph.nets.values()
                if n.matched_group == group and n.routed and n.path is not None]
    return [n for n in group if n.routed and n.path is not None]


def length_match(graph: DesignGraph, group: Union[str, Sequence[Net]],
                 tol_mm: float = MATCH_TOL_MM) -> Dict[str, float]:
    """Égalise les longueurs des nets du groupe par serpentins.

    Cible = max(longueurs du groupe), plafonnée par net.max_length_mm si défini.
    Retourne {net_id: longueur_finale_mm}.
    """
    nets = _resolve_group(graph, group)
    if len(nets) < 2:
        return {n.net_id: n.path.length() for n in nets if n.path is not None}
    lengths = {n.net_id: n.path.length() for n in nets}
    cap = min([n.max_length_mm for n in nets if n.max_length_mm is not None],
              default=float("inf"))
    target = min(max(lengths.values()), cap)

    for net in nets:
        current = lengths[net.net_id]
        extra = target - current
        if extra <= tol_mm or net.path is None:
            continue
        new_points = add_serpentine(list(net.path.points), extra)
        if new_points is None:
            log.warning("serpentin impossible sur %s (déficit %.2f mm)",
                        net.net_id, extra)
            continue
        net.path = RoutePath(net_id=net.net_id, points=new_points,
                             layer=net.path.layer, width_mm=net.path.width_mm,
                             vias=list(net.path.vias))
        lengths[net.net_id] = net.path.length()
        log.info("serpentin %s : %.2f → %.2f mm (cible %.2f)",
                 net.net_id, current, lengths[net.net_id], target)

    worst = max(lengths.values()) - min(lengths.values()) if lengths else 0.0
    log.info("length_match[%s] : %d nets, écart max %.2f mm (tol %.2f)",
             group if isinstance(group, str) else "<liste>", len(nets), worst, tol_mm)
    return lengths
