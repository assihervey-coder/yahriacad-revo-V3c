"""Boucle multi-physique complète — simule, applique les feedbacks via les
moteurs placement/router (imports LAZY pour éviter les cycles), re-simule.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.simulator.base import BaseSim
from services.simulator.multi_physics_loop.convergence import ConvergenceMonitor
from services.simulator.multi_physics_loop.coupling import MultiPhysicsCoupling
from services.simulator.power_integrity import PowerIntegritySim
from services.simulator.signal_integrity import SignalIntegritySim
from services.simulator.thermal_sim import ThermalSim

log = get_logger("simulator.feedback")


def default_sims() -> List[BaseSim]:
    """Jeu de sims par défaut de la boucle (thermique + SI + PI)."""
    return [ThermalSim(), SignalIntegritySim(), PowerIntegritySim()]


def run_loop(graph: DesignGraph, max_iters: int = 3,
             sims: Optional[List[BaseSim]] = None) -> Dict[str, Any]:
    """Boucle simuler → feedbacks → corriger → re-simuler (max `max_iters` tours).

    Feedbacks appliqués :
    - thermal fail  → éloigne les composants coupables du hotspot (place) puis
      passe d'optimisation locale ;
    - si fail       → dé-route les nets incriminés puis re-routage ciblé ;
    - pi fail       → élargit les pistes des rails fautifs puis re-routage.

    Imports des moteurs placement_engine/router FAITS DANS LA FONCTION (lazy)
    pour éviter les imports circulaires au chargement des packages.
    """
    # imports paresseux (moteurs géométriques)
    from services.placement_engine.optimizer import PlacementOptimizer
    from services.router.engine import RouterEngine
    from services.router.high_speed import MATCH_TOL_MM

    g = graph
    monitor = ConvergenceMonitor(tol=1e-3, window=3)
    coupling = MultiPhysicsCoupling()
    sims = sims or default_sims()
    history: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []

    for iteration in range(1, max_iters + 1):
        outcome = coupling.run(g, sims)
        metrics = {kind: (res.metrics.get("max_temp_c", 0.0) if kind == "thermal"
                          else res.metrics.get("worst_gamma", 0.0) if kind == "si"
                          else res.metrics.get("worst_ir_drop_mv", 0.0) if kind == "pi"
                          else float(len(res.notes)))
                   for kind, res in outcome["results"].items()}
        history.append({
            "iteration": iteration,
            "passed": outcome["passed"],
            "metrics": {k: round(v, 4) for k, v in metrics.items()},
            "feedbacks": outcome["feedbacks"],
        })
        converged = monitor.track(metrics)
        if outcome["passed"] or converged:
            log.info("boucle multi-physique : arrêt à l'itération %d (pass=%s, conv=%s)",
                     iteration, outcome["passed"], converged)
            break

        for fb in outcome["feedbacks"]:
            applied.append(_apply_feedback(g, fb, RouterEngine, PlacementOptimizer))
    else:
        log.warning("boucle multi-physique : max_iters=%d atteint sans convergence",
                    max_iters)

    return {
        "graph": g,
        "iterations": len(history),
        "history": history,
        "applied_feedbacks": applied,
        "converged": bool(monitor.converged),
        "monitor": monitor.summary(),
    }


def _apply_feedback(graph: DesignGraph, fb: Dict[str, Any],
                    RouterEngine, PlacementOptimizer) -> Dict[str, Any]:
    """Applique un feedback concret via les moteurs (retourne un journal)."""
    action = fb.get("action")
    entry: Dict[str, Any] = {"action": action, "source": fb.get("source")}

    if action == "replace_placement":
        hotspot = fb.get("hotspot")
        for ref in fb.get("components", []):
            if ref not in graph.components:
                continue
            comp = graph.get(ref)
            if hotspot:
                dx = comp.x - hotspot[0]
                dy = comp.y - hotspot[1]
                norm = math.hypot(dx, dy) or 1.0
                tx, ty = comp.x + dx / norm * 6.0, comp.y + dy / norm * 6.0
            else:
                tx, ty = comp.x + 6.0, comp.y + 6.0
            from services.router.topological import clamp_to_board, placement_free
            w, h = comp.bbox
            tx, ty = clamp_to_board(graph, tx, ty, w, h, 1.0)
            graph.place(ref, tx, ty, rotation=comp.rotation)
        graph2, score = PlacementOptimizer().optimize(graph, iterations=30)
        _copy_placement(graph, graph2)
        entry["detail"] = "composants éloignés du hotspot + optimisation locale"
    elif action in ("reroute", "widen_power_traces"):
        for nid in fb.get("nets", []):
            net = graph.nets.get(nid)
            if net is None:
                continue
            if action == "widen_power_traces" and net.path is not None:
                net.path.width_mm = max(net.path.width_mm * 1.5, 0.5)
            net.path = None
            net.routed = False
        result = RouterEngine().route_all(graph, strategy="auto")
        if result.graph is not None:
            _copy_nets(graph, result.graph)
        entry["detail"] = "nets re-routés par RouterEngine"
    else:
        entry["detail"] = "feedback non actionnable (ignoré)"
    log.info("feedback appliqué : %s (%s)", action, entry.get("detail"))
    return entry


def _copy_placement(dst: DesignGraph, src: DesignGraph) -> None:
    """Recopie positions/rotations de src vers dst (même référentiel)."""
    for ref, comp in src.components.items():
        if ref in dst.components:
            dst.place(ref, comp.x, comp.y, rotation=comp.rotation)


def _copy_nets(dst: DesignGraph, src: DesignGraph) -> None:
    """Recopie les paths/routed des nets de src vers dst."""
    for nid, net in src.nets.items():
        if nid in dst.nets:
            dst.nets[nid].path = net.path
            dst.nets[nid].routed = net.routed
