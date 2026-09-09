"""Couplage multi-physique — exécute les sims, consolide les feedbacks.

Chaque simulation passe par la voie β (`run_sim_smart`) : si un surrogate
neuronal entraîné couvre le kind demandé, l'inférence rapide (~µs) REMPLACE
le solveur complet (bêta) ; sinon le solveur complet tourne et alimente
l'apprentissage continu du surrogate (enregistrement + auto-train).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

from shared.utilities import get_logger, new_id

from services.design_core import DesignGraph

from services.simulator.base import BaseSim, SimResult
from services.simulator.surrogate_models.beta_path import run_sim_smart

log = get_logger("simulator.coupling")


class MultiPhysicsCoupling:
    """Exécute un ensemble de sims et détermine les feedbacks inter-domaines."""

    def run(self, graph: DesignGraph, sims: Sequence[BaseSim],
            surrogate_manager: Optional[Any] = None) -> Dict[str, Any]:
        """Retourne {"results": {kind: SimResult}, "feedbacks": [...], "passed": bool}.

        `surrogate_manager` (optionnel) active la voie β : surrogate entraîné
        → inférence rapide à la place du solveur complet.
        """
        t0 = time.perf_counter()
        results: Dict[str, SimResult] = {}
        beta_kinds: List[str] = []
        for sim in sims:
            try:
                result, beta_used = run_sim_smart(sim, graph,
                                                  manager=surrogate_manager)
                results[sim.sim_kind] = result
                if beta_used:
                    beta_kinds.append(sim.sim_kind)
            except Exception:  # une sim défaillante n'arrête pas la boucle
                log.exception("simulation %s en échec", sim.sim_kind)
                results[sim.sim_kind] = SimResult(
                    sim_kind=sim.sim_kind, metrics={}, passed=False,
                    runtime_s=0.0, notes=["exception pendant la simulation"])
        feedbacks = self._feedbacks(graph, results)
        passed = all(r.passed for r in results.values()) if results else True
        log.info("couplage multi-physique : %d sims (%d via β), %d feedback(s) (%.0f ms)",
                 len(results), len(beta_kinds), len(feedbacks),
                 (time.perf_counter() - t0) * 1000)
        return {
            "results": results,
            "feedbacks": feedbacks,
            "passed": passed,
            "beta_kinds": beta_kinds,
            "correlation_id": new_id("mp"),
        }

    # ----------------------------------------------------------------- private
    def _feedbacks(self, graph: DesignGraph,
                   results: Dict[str, SimResult]) -> List[Dict[str, Any]]:
        """Traduit les échecs en actions correctives concrètes pour les moteurs."""
        feedbacks: List[Dict[str, Any]] = []

        thermal = results.get("thermal")
        if thermal is not None and not thermal.passed:
            hotspot = thermal.metrics.get("hotspot")
            culprits = self._hotspot_components(graph, hotspot)
            feedbacks.append({
                "source": "thermal", "action": "replace_placement",
                "components": culprits,
                "hotspot": list(hotspot) if hotspot else None,
                "reason": (thermal.notes or ["hotspot > limite"])[0],
            })

        si = results.get("si")
        if si is not None and not si.passed:
            bad_nets = [nid for nid, rep in si.metrics.get("nets", {}).items()
                        if not rep.get("passed", True)]
            if bad_nets:
                feedbacks.append({
                    "source": "si", "action": "reroute",
                    "nets": bad_nets,
                    "reason": f"|Γ| ou mismatch hors tolérance ({len(bad_nets)} nets)",
                })

        pi = results.get("pi")
        if pi is not None and not pi.passed:
            bad_rails = [nid for nid, rep in pi.metrics.get("rails", {}).items()
                         if not rep.get("passed", True)]
            if bad_rails:
                feedbacks.append({
                    "source": "pi", "action": "widen_power_traces",
                    "nets": bad_rails,
                    "reason": f"chute IR > limite ({len(bad_rails)} rails)",
                })

        emi = results.get("emi")
        if emi is not None and not emi.passed:
            feedbacks.append({
                "source": "emi", "action": "reduce_loops",
                "reason": (emi.notes or ["boucles de courant excessives"])[0],
            })
        return feedbacks

    @staticmethod
    def _hotspot_components(graph: DesignGraph, hotspot, radius_mm: float = 8.0) -> List[str]:
        """Composants dissipateurs proches du hotspot (cibles d'un replacement)."""
        import math
        if not hotspot:
            return [c.ref for c in sorted(
                (c for c in graph.components.values() if c.power_w > 0.5),
                key=lambda c: -c.power_w)[:3]]
        culprits = []
        for comp in graph.components.values():
            if comp.power_w <= 0.2:
                continue
            if math.hypot(comp.x - hotspot[0], comp.y - hotspot[1]) <= radius_mm:
                culprits.append(comp.ref)
        return culprits or [c.ref for c in sorted(
            (c for c in graph.components.values() if c.power_w > 0.5),
            key=lambda c: -c.power_w)[:3]]
