"""Minimisation des vias — re-routage mono-couche des nets multi-vias."""
from __future__ import annotations

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net
from services.router.geometrical import MazeRouter
from services.router.topological import build_net_topology

log = get_logger("router.via_minimizer")


def _route_single_layer(graph: DesignGraph, net: Net, maze: MazeRouter,
                        layer: int, width_mm: float) -> list[Point] | None:
    """Tente de router TOUT le net (MST complet) sur une seule couche."""
    points: list[Point] = []
    for a, b in build_net_topology(graph, net):
        path = maze.route_pair(graph, net, a, b, layer, width_mm)
        if path is None:
            return None
        for p in path:
            if not points or points[-1].distance_to(p) > 1e-9:
                points.append(p)
    return points


def minimize(graph: DesignGraph, maze: MazeRouter | None = None,
             max_length_ratio: float = 1.5) -> int:
    """Ré-essaie les nets à ≥1 via sur une seule couche ; retourne les vias économisés.

    Un re-routage mono-couche n'est accepté que si sa longueur reste raisonnable
    (≤ `max_length_ratio` × l'ancienne) — sinon la route à vias est conservée.
    """
    maze = maze or MazeRouter(board_size=graph.board_size)
    saved = 0
    for net in list(graph.nets.values()):
        if not net.routed or net.path is None or not net.path.vias:
            continue
        old_vias = len(net.path.vias)
        old_len = net.path.length()
        width = net.path.width_mm
        # couche dominante : celle de la majorité des pads (sinon F.Cu)
        layer = 0
        points = _route_single_layer(graph, net, maze, layer, width)
        if points is None:
            continue
        new_len = sum(points[i].distance_to(points[i + 1])
                      for i in range(len(points) - 1))
        if new_len > old_len * max_length_ratio + 1e-9:
            continue
        net.path = RoutePath(net_id=net.net_id, points=points, layer=layer,
                             width_mm=width, vias=[])
        maze.observe_path(net.path)
        saved += old_vias
        log.debug("via_minimizer : %s %d via(s) économisé(s) (%.1f → %.1f mm)",
                  net.net_id, old_vias, old_len, new_len)
    if saved:
        log.info("via_minimizer : %d via(s) économisé(s) au total", saved)
    return saved
