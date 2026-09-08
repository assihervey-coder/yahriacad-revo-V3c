"""Paires différentielles — détection des appariements _P/_N et routage parallèle.

Le membre P est routé par A* ; le membre N reçoit le chemin décalé d'un gap
constant (bord-à-bord), avec extrémités recalées sur ses propres pads.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.geometrical import MazeRouter, offset_polyline
from services.router.topological import (
    build_net_topology,
    is_differential_net,
    net_pad_positions,
)

log = get_logger("router.differential")

_PAIR_SUFFIXES = ("_P", "_N", "_DP", "_DM", "_+", "_-", "+", "-")


def _pair_base(name: str) -> Optional[Tuple[str, str]]:
    """(base, polarity) si le nom se termine par un suffixe de paire, None sinon."""
    n = (name or "").strip()
    upper = n.upper()
    for suf in ("_P", "_DP"):
        if upper.endswith(suf):
            return upper[: -len(suf)], "P"
    for suf in ("_N", "_DM"):
        if upper.endswith(suf):
            return upper[: -len(suf)], "N"
    if upper.endswith("_+"):
        return upper[:-2], "P"
    if upper.endswith("_-"):
        return upper[:-2], "N"
    return None


def find_differential_pairs(graph: DesignGraph) -> List[Tuple[Net, Net]]:
    """Détecte les paires (P, N) : classe differential groupée par matched_group,
    sinon appariement par suffixe _P/_N (ou _DP/_DM) des noms de nets."""
    pairs: List[Tuple[Net, Net]] = []
    used: set[str] = set()

    diff_nets = [n for n in graph.nets.values() if is_differential_net(n)]

    # 1) par matched_group : 2 nets (ou plus) → on apparie P puis N
    by_group: Dict[str, List[Net]] = {}
    for net in diff_nets:
        if net.matched_group:
            by_group.setdefault(net.matched_group, []).append(net)
    for group, nets in sorted(by_group.items()):
        p = next((n for n in nets if _pair_base(n.name) and _pair_base(n.name)[1] == "P"), None)
        n_net = next((n for n in nets if n is not p and
                      (_pair_base(n.name) is None or _pair_base(n.name)[1] == "N")), None)
        if p is not None and n_net is not None:
            pairs.append((p, n_net))
            used.update((p.net_id, n_net.net_id))
        else:
            log.warning("groupe différentiel '%s' non appariable (%d nets)", group, len(nets))

    # 2) par suffixe de nom sur les nets différentiels restants
    remaining = [n for n in diff_nets if n.net_id not in used]
    by_base: Dict[str, Dict[str, Net]] = {}
    for net in remaining:
        base = _pair_base(net.name)
        if base is None:
            continue
        by_base.setdefault(base[0], {})[base[1]] = net
    for base, pol in sorted(by_base.items()):
        if "P" in pol and "N" in pol:
            pairs.append((pol["P"], pol["N"]))
    return pairs


class DifferentialPairRouter:
    """Route les deux membres d'une paire en parallèle avec espacement constant."""

    def __init__(self, maze: Optional[MazeRouter] = None, gap_mm: float = 0.45) -> None:
        self.maze = maze
        self.gap_mm = float(gap_mm)

    def route_pair(self, graph: DesignGraph, net_p: Net, net_n: Net,
                   width_mm: float = 0.2) -> bool:
        """Route net_p (A*) puis décale le chemin pour net_n. True si succès."""
        maze = self.maze or MazeRouter(board_size=graph.board_size)
        segments = build_net_topology(graph, net_p)
        if not segments:
            return False
        points: List[Point] = []
        for a, b in segments:
            path = maze.route_pair(graph, net_p, a, b, 0, width_mm)
            if path is None:
                return False
            for p in path:
                if not points or points[-1].distance_to(p) > 1e-9:
                    points.append(p)

        # membre N : chemin décalé, extrémités recalées sur ses vrais pads
        n_pads = [pos for _, pos in net_pad_positions(graph, net_n)]
        n_points = offset_polyline(points, width_mm + self.gap_mm)
        if n_pads:
            n_start = _nearest(n_pads, n_points[0])
            n_end = _nearest(list(reversed(n_pads)), n_points[-1])
            n_points = [n_start] + n_points[1:-1] + [n_end]
        net_p.path = RoutePath(net_id=net_p.net_id, points=points, layer=0,
                               width_mm=width_mm, vias=[])
        net_n.path = RoutePath(net_id=net_n.net_id, points=n_points, layer=0,
                               width_mm=width_mm, vias=[])
        net_p.routed = True
        net_n.routed = True
        maze.observe_path(net_p.path)
        maze.observe_path(net_n.path)
        log.info("paire différentielle %s/%s routée (gap %.2f mm, %.1f mm)",
                 net_p.name, net_n.name, self.gap_mm, net_p.path.length())
        return True


def _nearest(candidates: List[Point], target: Point) -> Point:
    return min(candidates, key=lambda p: p.distance_to(target))
