"""RouterEngine — pipeline complet de routage (topologie → A* → rip-up → match)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from shared.events import EventTypes, get_event_bus, make_event
from shared.utilities import get_logger, new_id

from services.design_core import DesignGraph, Net
from services.router.differential_pairs import DifferentialPairRouter, find_differential_pairs
from services.router.geometrical import MazeRouter
from services.router.high_speed import length_match
from services.router.impedance_control import assign_trace_widths
from services.router.route_optimizer import rip_up_and_reroute, route_net_segments
from services.router.topological import (
    class_rank,
    net_length_estimate,
)
from services.router.via_minimizer import minimize as minimize_vias

log = get_logger("router.engine")


@dataclass
class RoutingResult:
    """Résultat du pipeline de routage (métriques + graphe routé)."""

    routed: int
    failed: int
    total_length_mm: float
    vias: int
    duration_ms: float
    details: dict[str, object] = field(default_factory=dict)
    graph: DesignGraph | None = None     # copie routée (source de vérité inchangée)

    def to_dict(self) -> dict[str, object]:
        return {
            "routed": self.routed, "failed": self.failed,
            "total_length_mm": round(self.total_length_mm, 2),
            "vias": self.vias, "duration_ms": round(self.duration_ms, 2),
            "details": self.details,
        }


def _emit(event) -> None:
    """Publie un event (loop async existant → task, sinon run isolé)."""
    try:
        bus = get_event_bus()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(bus.publish(event))
        except RuntimeError:
            asyncio.run(bus.publish(event))
    except Exception:  # un event ne doit jamais casser le routage
        log.debug("émission event ignorée", exc_info=True)


class RouterEngine:
    """Cerveau décisionnel du routage : priorise, route, répare et égalise."""

    def __init__(self, grid_step: float = 0.25, clearance: float = 0.2,
                 via_penalty: float = 3.0, seed: int = 0) -> None:
        self.grid_step = grid_step
        self.clearance = clearance
        self.via_penalty = via_penalty

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _signal_layers(graph: DesignGraph) -> tuple[int, ...]:
        """Indices des couches de signal (fallback [0, 1])."""
        idx = tuple(ly.index for ly in graph.layers if ly.ltype in ("signal", "mixed"))
        return idx or (0, 1)

    def route_all(self, graph: DesignGraph, strategy: str = "auto",
                  widths: dict[str, float] | None = None) -> RoutingResult:
        """Route tous les nets sur une COPIE du graphe (l'original est intact).

        Pipeline : largeurs → tri (power, high_speed, default courts) →
        paires différentielles + A* par segment MST → rip-up/reroute des échecs →
        égalisation des longueurs (matched_group) → minimisation des vias.
        """
        t0 = time.perf_counter()
        g = graph.copy()
        widths = widths or assign_trace_widths(g)
        layers = self._signal_layers(g)
        maze = MazeRouter(board_size=g.board_size, grid_step=self.grid_step,
                          clearance=self.clearance, via_penalty=self.via_penalty)

        # ---- tri : power d'abord, puis high_speed/différentiel, puis courts
        nets_sorted = sorted(
            g.unrouted_nets(),
            key=lambda n: (class_rank(n), net_length_estimate(g, n)),
        )
        pairs = find_differential_pairs(g)
        pair_partner: dict[str, Net] = {}
        for p, n in pairs:
            pair_partner[p.net_id] = n
            pair_partner[n.net_id] = p

        failed: list[str] = []
        pair_router = DifferentialPairRouter(maze=maze)

        for net in nets_sorted:
            if not net.routed and net.net_id in pair_partner:
                partner = pair_partner[net.net_id]
                if partner.routed:
                    continue
                width = widths.get(net.net_id, 0.2)
                if pair_router.route_pair(g, net, partner, width, layers=layers):
                    continue
                failed.extend((net.net_id, partner.net_id))
                continue
            if net.routed:
                continue
            if not route_net_segments(g, net, maze, widths.get(net.net_id, 0.2), layers):
                failed.append(net.net_id)

        # ---- rip-up & reroute des échecs
        reroute_info: dict[str, object] = {}
        if failed:
            reroute_info = rip_up_and_reroute(g, failed, attempts=3, maze=maze,
                                              widths=widths, layers=layers)
            failed = list(reroute_info.get("still_failed", []))

        # ---- égalisation des longueurs par groupe apparié
        groups = sorted({n.matched_group for n in g.nets.values()
                         if n.matched_group and n.routed})
        matched: dict[str, dict[str, float]] = {}
        for grp in groups:
            matched[str(grp)] = length_match(g, str(grp))

        # ---- minimisation des vias (stratégie auto uniquement)
        vias_saved = 0
        if strategy == "auto":
            vias_saved = minimize_vias(g, maze=maze)

        routed_nets = [n for n in g.nets.values() if n.routed and n.path is not None]
        total_len = sum(n.path.length() for n in routed_nets)
        n_vias = sum(len(n.path.vias) for n in routed_nets)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        result = RoutingResult(
            routed=len(routed_nets),
            failed=len([n for n in g.nets.values() if not n.routed]),
            total_length_mm=total_len,
            vias=n_vias,
            duration_ms=duration_ms,
            details={
                "strategy": strategy,
                "widths_mm": {k: round(v, 3) for k, v in widths.items()},
                "failed_nets": failed,
                "differential_pairs": [[p.net_id, n.net_id] for p, n in pairs],
                "differential_pairs_quality": [r.to_dict() for r in pair_router.reports],
                "matched_groups": {k: {nid: round(v, 2) for nid, v in val.items()}
                                   for k, val in matched.items()},
                "vias_saved_by_minimizer": vias_saved,
                "rip_up": reroute_info,
                "maze_stats": maze.stats,
                "layers": list(layers),
            },
            graph=g,
        )
        _emit(make_event(
            EventTypes.ROUTING_PROPOSED,
            {
                "routed": result.routed, "failed": result.failed,
                "total_length_mm": round(total_len, 2), "vias": n_vias,
                "duration_ms": round(duration_ms, 2),
            },
            project_id=g.project_id, source="router",
            correlation_id=new_id("rt"),
        ))
        log.info("routage terminé : %d/%d nets, %.1f mm, %d vias (%.0f ms)",
                 result.routed, result.routed + result.failed, total_len,
                 n_vias, duration_ms)
        return result
