"""Optimiseur de routage — route un net complet (MST + A*) et rip-up/reroute."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.geometrical import MazeRouter
from services.router.topological import (
    build_net_topology,
    net_length_estimate,
    net_pad_positions,
)

log = get_logger("router.route_optimizer")


def route_net_segments(graph: DesignGraph, net: Net, maze: MazeRouter,
                       width_mm: float,
                       layers: Sequence[int] = (0, 1)) -> bool:
    """Route tous les segments MST d'un net (alternance de couches + vias si bloqué).

    Écrit Net.path (RoutePath) et Net.routed=True en cas de succès.
    """
    if len(net.pins) < 2:
        # net dégénéré : marqué routé (R à 1 pin = erreur ERC, pas du routage)
        pos = net_pad_positions(graph, net)
        net.path = RoutePath(net_id=net.net_id,
                             points=[pos[0][1]] if pos else [], layer=0,
                             width_mm=width_mm, vias=[])
        net.routed = True
        return True
    points: List[Point] = []
    vias: List[Tuple[Point, int, int]] = []
    for a, b in build_net_topology(graph, net):
        path: Optional[List[Point]] = None
        used_layer = layers[0] if layers else 0
        for lyr in layers:
            path = maze.route_pair(graph, net, a, b, lyr, width_mm)
            if path is not None:
                used_layer = lyr
                break
        if path is None:
            return False
        if used_layer != (layers[0] if layers else 0):
            # changement de couche : vias aux deux extrémités du segment
            vias.append((a, layers[0], used_layer))
            vias.append((b, used_layer, layers[0]))
        for p in path:
            if not points or points[-1].distance_to(p) > 1e-9:
                points.append(p)
    net.path = RoutePath(net_id=net.net_id, points=points,
                         layer=layers[0] if layers else 0, width_mm=width_mm,
                         vias=vias)
    net.routed = True
    maze.observe_path(net.path)
    return True


def _corridor(graph: DesignGraph, net_id: str, inflate: float = 2.0) -> Optional[Tuple[float, float, float, float]]:
    """BBox gonflée des pads d'un net — couloir de routage approximatif."""
    pos = [p for _, p in net_pad_positions(graph, graph.nets[net_id])]
    if not pos:
        return None
    xs = [p.x for p in pos]
    ys = [p.y for p in pos]
    return (min(xs) - inflate, min(ys) - inflate, max(xs) + inflate, max(ys) + inflate)


def _blocking_nets(graph: DesignGraph, failed_ids: Sequence[str],
                   max_per_net: int = 6) -> List[str]:
    """Nets routés dont les traces traversent le couloir des nets en échec."""
    blockers: List[str] = []
    for fid in failed_ids:
        rect = _corridor(graph, fid)
        if rect is None:
            continue
        x0, y0, x1, y1 = rect
        near: List[Tuple[float, str]] = []
        for other in graph.nets.values():
            if other.net_id == fid or not other.routed or other.path is None:
                continue
            for seg in other.path.segments():
                sx0 = min(seg.start.x, seg.end.x)
                sx1 = max(seg.start.x, seg.end.x)
                sy0 = min(seg.start.y, seg.end.y)
                sy1 = max(seg.start.y, seg.end.y)
                if not (sx1 < x0 or sx0 > x1 or sy1 < y0 or sy0 > y1):
                    near.append((other.path.length(), other.net_id))
                    break
        near.sort()
        blockers.extend(nid for _, nid in near[:max_per_net])
    return sorted(set(blockers))


def rip_up_and_reroute(graph: DesignGraph, failed_nets: Sequence[str],
                       attempts: int = 3, maze: Optional[MazeRouter] = None,
                       widths: Optional[Dict[str, float]] = None,
                       layers: Sequence[int] = (0, 1)) -> Dict[str, object]:
    """Dé-route les nets en échec + leurs bloqueurs, re-route dans un ordre
    différent (longueur croissante, rotation par tentative) et garde la meilleure
    configuration globale (nb de nets routés, puis longueur totale minimale).

    Retour : {"routed": [...], "still_failed": [...], "attempts": int}.
    """
    maze = maze or MazeRouter(board_size=graph.board_size)
    failed_ids = [fid for fid in failed_nets if fid in graph.nets]
    if not failed_ids:
        return {"routed": [], "still_failed": [], "attempts": 0}

    def unrout(nid: str) -> None:
        net = graph.nets[nid]
        net.path = None
        net.routed = False

    def snapshot() -> Dict[str, Tuple[Optional[RoutePath], bool]]:
        return {nid: (n.path, n.routed) for nid, n in graph.nets.items()}

    def restore(state: Dict[str, Tuple[Optional[RoutePath], bool]]) -> None:
        for nid, (path, routed) in state.items():
            net = graph.nets[nid]
            net.path, net.routed = path, routed

    order_base = sorted(failed_ids, key=lambda nid: net_length_estimate(graph, graph.nets[nid]))
    best_state: Optional[Dict[str, Tuple[Optional[RoutePath], bool]]] = None
    best_score: Tuple[int, float] = (-1, -math.inf)
    best_routed: List[str] = []

    for attempt in range(max(1, attempts)):
        # 1) rip-up : nets en échec + bloqueurs
        for nid in failed_ids:
            unrout(nid)
        blockers = [b for b in _blocking_nets(graph, failed_ids)
                    if graph.nets[b].routed and b not in failed_ids]
        for nid in blockers:
            unrout(nid)

        # 2) re-route les nets en échec (ordre tourné : longueur croissante)
        rot = attempt % max(1, len(order_base))
        order = order_base[rot:] + order_base[:rot]
        routed_now: List[str] = []
        for nid in order:
            net = graph.nets[nid]
            width = (widths or {}).get(nid, net.path.width_mm if net.path else 0.2)
            if route_net_segments(graph, net, maze, width, layers):
                routed_now.append(nid)

        # 3) re-route les bloqueurs dé-routés (longueur croissante)
        for nid in sorted(blockers, key=lambda b: net_length_estimate(graph, graph.nets[b])):
            if graph.nets[nid].routed:
                continue
            net = graph.nets[nid]
            width = (widths or {}).get(nid, net.path.width_mm if net.path else 0.2)
            if route_net_segments(graph, net, maze, width, layers):
                routed_now.append(nid)

        # 4) score global : nb nets routés puis −longueur totale
        n_routed = sum(1 for n in graph.nets.values() if n.routed)
        score = (n_routed, -graph.total_wire_length())
        if score > best_score:
            best_score = score
            best_state = snapshot()
            best_routed = list(routed_now)
            log.info("rip-up tentative %d : %d net(s) re-routé(s), routed=%d, len=%.1f mm",
                     attempt + 1, len(routed_now), n_routed, -score[1])

    if best_state is not None:
        restore(best_state)
    still_failed = [nid for nid in failed_ids if not graph.nets[nid].routed]
    return {"routed": best_routed, "still_failed": still_failed,
            "attempts": max(1, attempts)}
