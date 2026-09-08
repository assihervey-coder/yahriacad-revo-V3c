"""Simulation d'intégrité du signal — délai, réflexion |Γ| et appariement de longues.

Pour les nets high_speed/differential : délai = L/(c/√εeff), coefficient de
réflexion |Γ| = |(ZL − Z0)/(ZL + Z0)| (Z0 calculé depuis la largeur réelle),
écart de longueur dans les matched_group (tolérance 0.5 mm).
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List

from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.high_speed import MATCH_TOL_MM
from services.router.impedance_control import (
    DEFAULT_HEIGHT_UM,
    microstrip_z0,
    effective_er,
    propagation_delay_ns,
)
from services.router.topological import is_high_speed_net
from services.simulator.base import BaseSim, SimResult

log = get_logger("simulator.si")

GAMMA_LIMIT = 0.2
DEFAULT_ZL_OHM = 50.0
SPEED_OF_LIGHT = 299_792_458.0


class SignalIntegritySim(BaseSim):
    """Vérifie Γ, délai et mismatch de longueur des nets critiques."""

    sim_kind = "si"

    def __init__(self, gamma_limit: float = GAMMA_LIMIT,
                 mismatch_tol_mm: float = MATCH_TOL_MM,
                 height_um: float = DEFAULT_HEIGHT_UM) -> None:
        self.gamma_limit = gamma_limit
        self.mismatch_tol_mm = mismatch_tol_mm
        self.height_um = height_um

    def run(self, graph: DesignGraph) -> SimResult:
        t0 = time.perf_counter()
        notes: List[str] = []
        er = graph.layers[0].er if graph.layers else 4.3

        targets = [n for n in graph.nets.values()
                   if is_high_speed_net(n) and len(n.pins) >= 2]
        nets_report: Dict[str, Dict[str, Any]] = {}
        worst_gamma, max_mismatch = 0.0, 0.0
        n_fail = 0

        for net in targets:
            length_mm = net.path.length() if net.path is not None else _estimate_length(graph, net)
            width_mm = net.path.width_mm if net.path is not None else 0.2
            z0 = microstrip_z0(width_mm, er, self.height_um)
            zl = float(net.impedance_target_ohm or DEFAULT_ZL_OHM)
            gamma = abs((zl - z0) / (zl + z0))
            e_eff = effective_er(width_mm, er, self.height_um)
            delay_ns = propagation_delay_ns(length_mm, er, width_mm, self.height_um)
            ok = gamma < self.gamma_limit
            entry: Dict[str, Any] = {
                "length_mm": round(length_mm, 2),
                "width_mm": round(width_mm, 3),
                "z0_ohm": round(z0, 1),
                "zl_ohm": zl,
                "gamma": round(gamma, 3),
                "delay_ns": round(delay_ns, 3),
                "er_eff": round(e_eff, 3),
                "mismatch_mm": None,
                "passed": ok,
            }
            nets_report[net.net_id] = entry
            worst_gamma = max(worst_gamma, gamma)
            if not ok:
                n_fail += 1
                notes.append(f"{net.name or net.net_id} : |Γ|={gamma:.2f} "
                             f"(Z0 {z0:.0f} Ω vs cible {zl:.0f} Ω) — ajuster la largeur")

        # mismatch au sein des groupes appariés
        groups: Dict[str, List[Net]] = {}
        for net in targets:
            if net.matched_group:
                groups.setdefault(net.matched_group, []).append(net)
        for group, nets in sorted(groups.items()):
            lengths = [nets_report[n.net_id]["length_mm"] for n in nets]
            spread = max(lengths) - min(lengths) if lengths else 0.0
            cap = min([n.max_length_mm for n in nets if n.max_length_mm is not None],
                      default=math.inf)
            spread = max(spread, max(lengths) - cap if lengths and cap < math.inf else 0.0)
            for n in nets:
                nets_report[n.net_id]["mismatch_mm"] = round(spread, 3)
                if spread > self.mismatch_tol_mm:
                    nets_report[n.net_id]["passed"] = False
                    n_fail += 1
                    notes.append(f"groupe {group} : écart {spread:.2f} mm > "
                                 f"{self.mismatch_tol_mm} mm — ajouter un serpentin")
            max_mismatch = max(max_mismatch, spread)

        passed = n_fail == 0
        metrics: Dict[str, Any] = {
            "n_checked": len(targets),
            "n_failed": n_fail,
            "worst_gamma": round(worst_gamma, 3),
            "max_mismatch_mm": round(max_mismatch, 3),
            "nets": nets_report,
        }
        if not targets:
            notes.append("aucun net high_speed/differential : rien à vérifier")
        log.info("SI : %d nets, pire Γ=%.3f, mismatch=%.2f mm → %s",
                 len(targets), worst_gamma, max_mismatch, "PASS" if passed else "FAIL")
        return SimResult(sim_kind=self.sim_kind, metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)


def _estimate_length(graph: DesignGraph, net: Net) -> float:
    """Longueur estimée d'un net non routé (MST topologique)."""
    from services.router.topological import net_length_estimate
    return net_length_estimate(graph, net)
