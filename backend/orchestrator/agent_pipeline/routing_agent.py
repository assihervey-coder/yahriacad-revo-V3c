"""RoutingAgent — routage des nets via RouterEngine."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import get_field, set_field, try_import
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema


class RoutingAgent(BaseAgent):
    """Étape `route` : RouterEngine.route_all → révision + journal des échecs."""

    role = AgentRole.ROUTING
    description = "Route les nets (A* bicouche via router, repli manhattan)."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.ROUTING, "routing", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("route_all", "route", "route_net", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")

        routed, failed, total_length = 0, [], 0.0
        engine_used = "fallback_manhattan"

        mods = try_import("services.router", ["RouterEngine"])
        cls = mods.get("RouterEngine")
        if cls is not None:
            try:
                try:
                    engine = cls()
                except TypeError:
                    engine = cls()
                result = engine.route_all(graph)
                routed = int(get_field(result, "routed", default=0) or 0)
                failed = [str(f) for f in (get_field(result, "failed", default=[]) or [])]
                total_length = float(get_field(result, "total_length_mm", default=0.0) or 0.0)
                engine_used = "router_engine"
                new_graph = get_field(result, "graph", default=None)
                if new_graph is not None:
                    context["graph"] = new_graph
            except Exception as exc:
                self.log.debug("RouterEngine indisponible: %s", exc)

        graph = context.get("graph") or graph
        if engine_used == "fallback_manhattan":
            routed, failed, total_length = self._fallback_route(graph)

        stats = get_field(graph, "stats", default=None)
        stats = call_probe(graph, "stats") if callable(getattr(graph, "stats", None)) else stats
        rev = self.commit(context, f"routage ({engine_used}) — {routed} nets")
        output: Dict[str, Any] = {
            "engine": engine_used,
            "routed": routed,
            "failed": failed,
            "total_length_mm": round(total_length, 3),
        }
        if stats:
            output["graph_stats"] = stats
        if rev is not None:
            output["revision"] = rev
        context["routing_failures"] = failed
        self.record_decision(context, "routage",
                             f"{routed} nets routés, {len(failed)} échecs, "
                             f"{total_length:.1f} mm", confidence=0.8 if not failed else 0.55)
        self.emit("routing.proposed", {"routed": routed, "failed": failed,
                                       "engine": engine_used}, context)
        return self.succeeded(context, output,
                              confidence=0.8 if not failed else 0.55,
                              rationale=f"routage {engine_used}: {routed} nets, "
                                        f"{len(failed)} échecs")

    def _fallback_route(self, graph: Any) -> Tuple[int, List[str], float]:
        """Repli : longueur manhattan par net, marquage routed si service absent."""
        comps = get_field(graph, "components", default={}) or {}
        nets = get_field(graph, "nets", default={}) or {}
        routed, failed, total = 0, [], 0.0
        for net_id, net in nets.items():
            pins = get_field(net, "pins", default=[]) or []
            points: List[Tuple[float, float]] = []
            for pin in pins:
                try:
                    ref = str(pin[0] if isinstance(pin, (list, tuple)) else get_field(pin, "ref", default=""))
                except Exception:
                    continue
                comp = comps.get(ref)
                if comp is not None:
                    points.append((float(get_field(comp, "x", "x_mm", default=0.0) or 0.0),
                                   float(get_field(comp, "y", "y_mm", default=0.0) or 0.0)))
            if len(points) < 2:
                failed.append(str(net_id))
                continue
            length = 0.0
            for i in range(1, len(points)):
                length += abs(points[i][0] - points[i - 1][0]) + abs(points[i][1] - points[i - 1][1])
            total += length
            set_field(net, "routed", True)
            set_field(net, "length_mm", round(length, 3))
            routed += 1
        return routed, failed, total
