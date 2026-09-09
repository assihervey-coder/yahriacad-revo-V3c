"""PlacementEngine — orchestration des stratégies de placement."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from shared.events import EventTypes, get_event_bus, make_event
from shared.utilities import get_logger, new_id

from services.design_core import DesignGraph
from services.placement_engine.constraint_placement import ConstraintPlacer
from services.placement_engine.initial_placement import InitialPlacer
from services.placement_engine.mechanical_placement import MechanicalPlacer
from services.placement_engine.optimizer import PlacementOptimizer
from services.placement_engine.rl_placement import RLPlacer
from services.placement_engine.thermal_placement import ThermalPlacer
from services.router.topological import hpwl_wire_length

log = get_logger("placement.engine")


@dataclass
class PlacementResult:
    """Résultat du placement : graphe placé + métriques d'exécution."""

    graph: DesignGraph
    strategy_used: str
    score: float              # HPWL estimé (mm)
    iterations: int
    duration_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy_used": self.strategy_used,
            "score_mm": round(self.score, 2),
            "iterations": self.iterations,
            "duration_ms": round(self.duration_ms, 2),
        }


def _emit(event) -> None:
    """Publie un event (task si boucle async existante, sinon boucle isolée)."""
    try:
        bus = get_event_bus()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(bus.publish(event))
        except RuntimeError:
            asyncio.run(bus.publish(event))
    except Exception:
        log.debug("émission event ignorée", exc_info=True)


class PlacementEngine:
    """Façade unique du placement : stratégie auto = initial → optimizer →
    passes mécanique/contraintes/thermique."""

    def __init__(self, policy=None, seed: int = 0) -> None:
        self.policy = policy
        self.seed = seed

    def place_all(self, graph: DesignGraph, strategy: str = "auto",
                  constraints: dict | None = None,
                  iterations: int = 100) -> PlacementResult:
        """Place tous les composants sur une COPIE du graphe et retourne le résultat."""
        t0 = time.perf_counter()
        iterations_used = 0
        g = graph.copy()

        if strategy in ("auto", "initial"):
            g = InitialPlacer().place(g)
            if strategy == "auto":
                g, score = PlacementOptimizer().optimize(g, iterations=min(iterations, 60))
                iterations_used += min(iterations, 60)
                g = MechanicalPlacer().place(g, constraints=constraints)
                g = ConstraintPlacer().place(g, constraints=constraints)
                g = ThermalPlacer().place(g, constraints=constraints)
                g, score = PlacementOptimizer().optimize(g, iterations=min(iterations, 40))
                iterations_used += min(iterations, 40)
        elif strategy == "rl":
            g = InitialPlacer(seed=self.seed).place(g)
            g = RLPlacer(policy=self.policy, seed=self.seed).place(g)
        elif strategy == "optimizer":
            g, score = PlacementOptimizer().optimize(g, iterations=iterations)
            iterations_used += iterations
        elif strategy == "constraint":
            g = ConstraintPlacer().place(g, constraints=constraints)
        elif strategy == "mechanical":
            g = MechanicalPlacer().place(g, constraints=constraints)
        elif strategy == "thermal":
            g = ThermalPlacer().place(g, constraints=constraints)
        else:
            raise ValueError(f"stratégie de placement inconnue : {strategy}")

        score = hpwl_wire_length(g)
        duration_ms = (time.perf_counter() - t0) * 1000.0
        _emit(make_event(
            EventTypes.PLACEMENT_PROPOSED,
            {
                "strategy": strategy, "score_mm": round(score, 2),
                "components": len(g.components), "duration_ms": round(duration_ms, 2),
            },
            project_id=g.project_id, source="placement_engine",
            correlation_id=new_id("pl"),
        ))
        log.info("placement '%s' : %d composants, HPWL %.1f mm (%.0f ms)",
                 strategy, len(g.components), score, duration_ms)
        return PlacementResult(graph=g, strategy_used=strategy, score=score,
                               iterations=iterations_used, duration_ms=duration_ms)
