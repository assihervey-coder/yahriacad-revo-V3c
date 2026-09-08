"""Simulation d'intégrité de puissance — chute IR sur les rails.

Résistance de piste : R/mm = ρ_cu/(w·h) (cuivre 35 µm), courant estimé par la
somme des power_w des composants alimentés / tension du rail. Droop = R·I.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.topological import is_power_net, voltage_of_net
from services.simulator.base import BaseSim, SimResult

log = get_logger("simulator.pi")

RHO_CU = 1.72e-8          # Ω·m
COPPER_UM = 35.0          # épaisseur cuivre standard
IR_DROP_LIMIT_MV = 50.0
DEFAULT_VOLTAGE_V = 3.3


class PowerIntegritySim(BaseSim):
    """Chute ohmique rail par rail (droop = R·I)."""

    sim_kind = "pi"

    def __init__(self, copper_um: float = COPPER_UM,
                 ir_drop_limit_mv: float = IR_DROP_LIMIT_MV) -> None:
        self.copper_um = copper_um
        self.ir_drop_limit_mv = ir_drop_limit_mv

    def run(self, graph: DesignGraph) -> SimResult:
        t0 = time.perf_counter()
        notes: List[str] = []
        rails: Dict[str, Dict[str, Any]] = {}
        worst_mv = 0.0
        worst_rail: str | None = None

        for net in graph.nets.values():
            if not is_power_net(net) or len(net.pins) < 2:
                continue
            cls = (net.class_name or "").lower()
            if cls in ("gnd", "ground"):
                continue      # masse : référence, pas de chute mesurée ici
            voltage = voltage_of_net(net, DEFAULT_VOLTAGE_V)
            width_mm = net.path.width_mm if net.path is not None else 0.5
            length_mm = net.path.length() if net.path is not None else _rail_length(graph, net)
            # R par mm : ρ/(w·h), normalisé en mΩ/mm
            w_m = max(width_mm, 0.05) * 1e-3
            h_m = self.copper_um * 1e-6
            r_per_mm_mohm = RHO_CU / (w_m * h_m) * 1e-3 * 1000.0
            resistance_mohm = r_per_mm_mohm * length_mm
            # courant = Σ power_w des composants alimentés par ce rail / tension
            load_w = 0.0
            for ref, _pad in net.pins:
                comp = graph.components.get(ref)
                if comp is not None:
                    load_w += comp.power_w
            current_a = load_w / max(voltage, 0.1)
            drop_mv = resistance_mohm * current_a
            ok = drop_mv < self.ir_drop_limit_mv
            rails[net.net_id] = {
                "name": net.name,
                "voltage_v": voltage,
                "length_mm": round(length_mm, 2),
                "width_mm": round(width_mm, 3),
                "resistance_mohm": round(resistance_mohm, 3),
                "current_a": round(current_a, 3),
                "ir_drop_mv": round(drop_mv, 2),
                "passed": ok,
            }
            if drop_mv > worst_mv:
                worst_mv, worst_rail = drop_mv, net.name or net.net_id
            if not ok:
                notes.append(
                    f"rail {net.name or net.net_id} : chute {drop_mv:.1f} mV > "
                    f"{self.ir_drop_limit_mv} mV (R={resistance_mohm:.1f} mΩ, "
                    f"I={current_a:.2f} A) — élargir la piste ou rapprocher le VRM")

        passed = all(r["passed"] for r in rails.values()) if rails else True
        if not rails:
            notes.append("aucun rail d'alimentation à 2+ pins : rien à vérifier")
        metrics: Dict[str, Any] = {
            "worst_ir_drop_mv": round(worst_mv, 2),
            "worst_rail": worst_rail,
            "limit_mv": self.ir_drop_limit_mv,
            "rails": rails,
        }
        log.info("PI : pire chute %.1f mV (%s) → %s",
                 worst_mv, worst_rail, "PASS" if passed else "FAIL")
        return SimResult(sim_kind=self.sim_kind, metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)


def _rail_length(graph: DesignGraph, net: Net) -> float:
    """Longueur approximative d'un rail non routé (MST)."""
    from services.router.topological import net_length_estimate
    return net_length_estimate(graph, net)
