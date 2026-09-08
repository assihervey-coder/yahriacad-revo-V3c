"""PlacementAgent — placement des composants via PlacementEngine."""
from __future__ import annotations

import math
from typing import Any, Dict

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import get_field, set_field, try_import
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema


class PlacementAgent(BaseAgent):
    """Étape `place` : PlacementEngine.place_all → nouveau graphe + révision."""

    role = AgentRole.PLACEMENT
    description = "Place les composants (recuit/RL via placement_engine, repli grille)."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.PLACEMENT, "placement", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("place_all", "place", "optimize", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte (étape select manquante ?)")
        params = context.get("params") or {}
        strategy = str(params.get("strategy") or "auto")
        score = 0.0
        strategy_used = strategy
        engine_used = "fallback_grid"

        mods = try_import("services.placement_engine", ["PlacementEngine"])
        cls = mods.get("PlacementEngine")
        if cls is not None:
            try:
                try:
                    engine = cls()
                except TypeError:
                    engine = cls()
                result = None
                try:
                    result = engine.place_all(graph, strategy=strategy)
                except TypeError:
                    result = engine.place_all(graph)
                new_graph = get_field(result, "graph", default=None) or graph
                score = float(get_field(result, "score", default=0.0) or 0.0)
                strategy_used = str(get_field(result, "strategy_used", default=strategy) or strategy)
                context["graph"] = new_graph
                engine_used = "placement_engine"
            except Exception as exc:
                self.log.debug("PlacementEngine indisponible: %s", exc)

        if engine_used == "fallback_grid":
            self._fallback_grid(context["graph"])
            strategy_used = f"grid_fallback({strategy})"
            score = 0.5

        stats = call_probe(context["graph"], "stats") or {}
        rev = self.commit(context, f"placement ({strategy_used})")
        output = {
            "strategy": strategy_used,
            "engine": engine_used,
            "score": round(score, 4),
            "graph_stats": stats,
        }
        if rev is not None:
            output["revision"] = rev
        self.record_decision(context, "placement",
                             f"stratégie {strategy_used}, score {score:.3f}", confidence=0.75)
        self.record_tradeoff(context, "placement", strategy_used, "manual",
                             "placement automatisé optimisant HPWL")
        self.emit("placement.proposed", {"strategy": strategy_used, "score": round(score, 4)}, context)
        return self.succeeded(context, output, confidence=0.75 if engine_used != "fallback_grid" else 0.5,
                              rationale=f"placement {strategy_used}")

    def _fallback_grid(self, graph: Any) -> None:
        """Placement en grille — repli déterministe si placement_engine est absent."""
        comps = get_field(graph, "components", default={}) or {}
        if not comps:
            return
        refs = sorted(comps.keys())
        cols = max(1, int(math.ceil(math.sqrt(len(refs)))))
        pitch = 12.0
        margin = 8.0
        for index, ref in enumerate(refs):
            x = margin + (index % cols) * pitch
            y = margin + (index // cols) * pitch
            try:
                graph.place(ref, x, y, 0.0)
            except Exception:
                try:
                    set_comp = comps.get(ref)
                    if set_comp is not None:
                        set_field(set_comp, "x", x)
                        set_field(set_comp, "y", y)
                except Exception:
                    continue
