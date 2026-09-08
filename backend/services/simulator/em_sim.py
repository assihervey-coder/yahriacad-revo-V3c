"""Simulation CEM (proxy) — capacité des plans, couplage entre traces parallèles,
boucles de courant PWR→GND (surface d'antenne d'émission).
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

from shared.geometry import Point, Segment

from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.geometrical import segment_segment_distance
from services.router.topological import is_high_speed_net, is_power_net
from services.simulator.base import BaseSim, SimResult

log = get_logger("simulator.emi")

EPS0 = 8.8541878128e-12      # F/m
DIELECTRIC_MM = 0.21         # séparation prépreg typique entre plans adjacents
CROSSTALK_K = 0.15           # constante de couplage (mm²) — proxy empirique
CROSSTALK_LIMIT_DB = -15.0
LOOP_AREA_LIMIT_MM2 = 1500.0
MAX_SEGMENT_PAIRS = 5000


class EMIProxySim(BaseSim):
    """Proxy CEM analytique : plans (C = ε₀εᵣA/d), crosstalk ~ k/d², boucles."""

    sim_kind = "emi"

    def __init__(self, dielectric_mm: float = DIELECTRIC_MM,
                 crosstalk_limit_db: float = CROSSTALK_LIMIT_DB,
                 loop_area_limit_mm2: float = LOOP_AREA_LIMIT_MM2) -> None:
        self.dielectric_mm = dielectric_mm
        self.crosstalk_limit_db = crosstalk_limit_db
        self.loop_area_limit_mm2 = loop_area_limit_mm2

    # ------------------------------------------------------------------ public
    def run(self, graph: DesignGraph) -> SimResult:
        t0 = time.perf_counter()
        notes: List[str] = []

        plane_cap_nf = self._plane_capacitance_nf(graph, notes)
        worst_xtalk_db, worst_pair = self._worst_crosstalk_db(graph)
        loop_area = self._loop_area_mm2(graph, notes)

        passed = (worst_xtalk_db <= self.crosstalk_limit_db
                  and loop_area <= self.loop_area_limit_mm2)
        if worst_xtalk_db > self.crosstalk_limit_db:
            notes.append(
                f"crosstalk estimé {worst_xtalk_db:.1f} dB > {self.crosstalk_limit_db} dB "
                f"entre {worst_pair[0]} et {worst_pair[1]} — élargir l'espacement")
        if loop_area > self.loop_area_limit_mm2:
            notes.append(
                f"boucle de retour estimée {loop_area:.0f} mm² > "
                f"{self.loop_area_limit_mm2} mm² — rapprocher le plan de masse")

        metrics: Dict[str, Any] = {
            "plane_capacitance_nf": round(plane_cap_nf, 3),
            "worst_crosstalk_db": round(worst_xtalk_db, 2),
            "worst_crosstalk_pair": list(worst_pair) if worst_pair else None,
            "estimated_loop_area_mm2": round(loop_area, 1),
            "dielectric_mm": self.dielectric_mm,
        }
        log.info("CEM proxy : C_plan=%.2f nF, crosstalk=%.1f dB, boucles=%.0f mm² → %s",
                 plane_cap_nf, worst_xtalk_db, loop_area, "PASS" if passed else "FAIL")
        return SimResult(sim_kind=self.sim_kind, metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)

    # ----------------------------------------------------------------- private
    def _plane_capacitance_nf(self, graph: DesignGraph, notes: List[str]) -> float:
        """C = ε₀·εᵣ·A/d entre les deux plans les plus proches (ground/power)."""
        planes = [l for l in graph.layers if l.ltype in ("ground", "power")]
        if len(planes) >= 2:
            er = planes[0].er
        else:
            er = graph.layers[0].er if graph.layers else 4.3
            notes.append("pas de plans dédiés : cap F.Cu/B.Cu utilisé comme proxy")
        area_m2 = graph.board_size[0] * graph.board_size[1] * 1e-6
        d_m = self.dielectric_mm * 1e-3
        return EPS0 * er * area_m2 / d_m * 1e9

    def _worst_crosstalk_db(self, graph: DesignGraph) -> Tuple[float, Tuple[str, str]]:
        """Crosstalk proxy entre traces parallèles d'un même layer : k/d² (dB)."""
        nets = [n for n in graph.nets.values() if n.path is not None]
        aggressors = [n for n in nets if is_high_speed_net(n) or is_power_net(n)] or nets
        worst_db = -120.0
        worst_pair: Tuple[str, str] = ("", "")
        budget = MAX_SEGMENT_PAIRS
        for i, aggr in enumerate(aggressors):
            for vict in nets:
                if budget <= 0:
                    break
                if vict.net_id == aggr.net_id or vict.path is None:
                    continue
                d = self._min_distance(aggr.path.segments(), vict.path.segments(),
                                       budget_ref=[budget])
                budget -= 1
                if d is None:
                    continue
                d_eff = max(d, 0.2)
                coupling = CROSSTALK_K / (d_eff * d_eff)
                db = 20.0 * math.log10(max(coupling, 1e-9))
                if db > worst_db:
                    worst_db, worst_pair = db, (aggr.name or aggr.net_id,
                                                vict.name or vict.net_id)
        return worst_db, worst_pair

    @staticmethod
    def _min_distance(segs_a, segs_b, budget_ref) -> float | None:
        """Distance minimale entre deux ensembles de segments (bbox early-exit)."""
        best: float | None = None
        for sa in segs_a:
            ax0 = min(sa.start.x, sa.end.x)
            ax1 = max(sa.start.x, sa.end.x)
            ay0 = min(sa.start.y, sa.end.y)
            ay1 = max(sa.start.y, sa.end.y)
            for sb in segs_b:
                if budget_ref[0] <= 0:
                    return best
                budget_ref[0] -= 1
                bx0 = min(sb.start.x, sb.end.x)
                bx1 = max(sb.start.x, sb.end.x)
                by0 = min(sb.start.y, sb.end.y)
                by1 = max(sb.start.y, sb.end.y)
                if bx0 > ax1 + 5.0 or bx1 < ax0 - 5.0 or by0 > ay1 + 5.0 or by1 < ay0 - 5.0:
                    continue    # early exit bbox : au-delà de 5 mm le couplage est nul
                d = segment_segment_distance(sa, sb)
                if best is None or d < best:
                    best = d
                    if best < 0.25:
                        return best
        return best

    def _loop_area_mm2(self, graph: DesignGraph, notes: List[str]) -> float:
        """Σ aire des boucles de courant : longueur × distance au chemin de retour."""
        gnd_paths = [n.path for n in graph.nets.values()
                     if n.path is not None and (n.class_name or "").lower() in ("gnd", "ground")]
        if not gnd_paths:
            gnd_paths = [n.path for n in graph.nets.values()
                         if n.path is not None and (n.name or "").upper().startswith("GND")]
        if not gnd_paths:
            notes.append("pas de retour GND routé : boucle estimée sur retour lointain (5 mm)")
        total = 0.0
        for net in graph.nets.values():
            if net.path is None or not is_power_net(net):
                continue
            if (net.class_name or "").lower() in ("gnd", "ground"):
                continue
            for seg in net.path.segments():
                if gnd_paths:
                    d = self._min_distance([seg], (s for p in gnd_paths for s in p.segments()),
                                           budget_ref=[200])
                    d_eff = max(d if d is not None else 5.0, 0.2)
                else:
                    d_eff = 5.0
                total += seg.length() * min(d_eff, 10.0)
        return total
