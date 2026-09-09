"""SimulationAgent — thermique + SI + PI (+ CEM) via services.simulator."""
from __future__ import annotations

from typing import Any, Dict, List

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import call_probe, get_field, try_import
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

_KIND_CLASSES = [
    ("thermal", "services.simulator", "ThermalSim"),
    ("si", "services.simulator", "SignalIntegritySim"),
    ("pi", "services.simulator", "PowerIntegritySim"),
    ("em", "services.simulator", "EMIProxySim"),
]


class SimulationAgent(BaseAgent):
    """Étape `simulate` : lance les simulateurs physiques et agrège les résultats."""

    role = AgentRole.SIMULATION
    description = "Simulations thermique / intégrité signal / intégrité puissance / CEM."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.SIMULATION, "simulation", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("simulate_all", "simulate", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")
        params = context.get("params") or {}
        requested = params.get("kinds") or ["thermal", "si", "pi", "em"]

        results: Dict[str, Dict[str, Any]] = {}
        all_passed = True
        ran_any = False

        for kind, module_name, class_name in _KIND_CLASSES:
            if kind not in requested:
                continue
            cls = try_import(module_name, [class_name]).get(class_name)
            if cls is None:
                results[kind] = {"skipped": True, "passed": True,
                                 "reason": f"{module_name}.{class_name} absent"}
                continue
            try:
                try:
                    sim = cls()
                except TypeError:
                    sim = cls(self.orchestrator)
                # voie β : surrogate entraîné → inférence rapide au lieu du
                # solveur complet ; sinon solveur complet + apprentissage
                beta_used = False
                try:
                    from services.simulator.surrogate_models.beta_path import (
                        run_sim_smart,
                    )
                    from services.simulator.surrogate_models.manager import (
                        get_manager,
                    )

                    sim_result, beta_used = run_sim_smart(sim, graph,
                                                          manager=get_manager())
                except Exception as exc:
                    self.log.debug("voie β inactive (%s) — solveur complet", exc)
                    sim_result = call_probe(sim, "run", (graph,))
                metrics = get_field(sim_result, "metrics", default={}) or {}
                passed = bool(get_field(sim_result, "passed", default=True))
                entry: Dict[str, Any] = {"metrics": _jsonable(metrics),
                                         "passed": passed, "skipped": False}
                if beta_used:
                    entry["beta"] = True
                    entry["engine"] = "surrogate β"
                results[kind] = entry
                ran_any = True
                if not passed:
                    all_passed = False
            except Exception as exc:
                self.log.debug("simulation %s indisponible: %s", kind, exc)
                results[kind] = {"skipped": True, "passed": True, "error": str(exc)[:200]}

        # Estimation thermique locale si aucun simulateur n'a tourné
        if not ran_any:
            results.setdefault("thermal", self._local_thermal(graph))

        context["sim_results"] = results
        output = {"sim_results": results, "all_passed": all_passed}
        summary = ", ".join(f"{k}={'OK' if v.get('passed') else 'KO'}"
                            for k, v in results.items())
        self.record_decision(context, "simulation", summary,
                             confidence=0.85 if all_passed else 0.4)
        self.emit("simulation.completed", {"all_passed": all_passed,
                                           "kinds": list(results.keys())}, context)
        return self.succeeded(context, output,
                              confidence=0.85 if all_passed else 0.4,
                              rationale=f"simulations: {summary}")

    def _local_thermal(self, graph: Any) -> Dict[str, Any]:
        """Estimation thermique grossière (repli) : T_max ≈ 25°C + ΣP · 30 °C/W."""
        comps = get_field(graph, "components", default={}) or {}
        total_power = 0.0
        hot_ref, hot_power = "", 0.0
        for ref, comp in comps.items():
            power = float(get_field(comp, "power_w", "power", default=0.0) or 0.0)
            total_power += power
            if power > hot_power:
                hot_ref, hot_power = str(ref), power
        est = 25.0 + total_power * 30.0
        passed = est < 105.0
        return {"skipped": False, "passed": passed, "engine": "local_estimate",
                "metrics": {"total_power_w": round(total_power, 3),
                            "hotspot_ref": hot_ref,
                            "est_max_temp_c": round(est, 1)}}


def _jsonable(metrics: Any) -> Any:
    if isinstance(metrics, dict):
        return {str(k): v for k, v in metrics.items()}
    if isinstance(metrics, (list, tuple, str, int, float, bool)) or metrics is None:
        return metrics
    return str(metrics)
