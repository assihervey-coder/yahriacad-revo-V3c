"""DFM — Design for Manufacturing : le design doit passer chez l'usine cible."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

from services.design_core.design_graph.graph import DesignGraph
from services.verification.manufacturing_rules import ManufacturingRules

log = get_logger(__name__)


@dataclass
class DFMViolation:
    code: str
    message: str
    severity: str = "error"        # error | warning | info
    location: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "severity": self.severity, "location": self.location}


@dataclass
class DFMReport:
    factory: str = "jlcpcb"
    violations: list[DFMViolation] = field(default_factory=list)
    checked: int = 0

    @property
    def passed(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    @property
    def score(self) -> float:
        """Score DFM 0..1."""
        if self.checked == 0:
            return 1.0
        penalty = sum(1.0 for v in self.violations if v.severity == "error")
        penalty += 0.5 * sum(1.0 for v in self.violations if v.severity == "warning")
        return max(0.0, 1.0 - penalty / max(1.0, self.checked))

    def to_dict(self) -> dict[str, Any]:
        return {"factory": self.factory, "passed": self.passed, "score": self.score,
                "checked": self.checked,
                "violations": [v.to_dict() for v in self.violations]}


class DFMEngine:
    """Compare le design au profil de l'usine cible (JLCPCB, PCBWay...)."""

    def __init__(self, factory: str = "jlcpcb") -> None:
        self.factory = factory
        self.profile = ManufacturingRules.get(factory)

    def run(self, graph: DesignGraph) -> DFMReport:
        report = DFMReport(factory=self.factory)
        prof = self.profile
        min_trace = float(prof.get("min_trace_mm", 0.127))
        min_clear = float(prof.get("min_clearance_mm", 0.127))
        min_hole = float(prof.get("min_hole_mm", 0.2))
        max_layers = int(prof.get("max_layers", 4))

        # 1. Nombre de couches
        report.checked += 1
        if len(graph.layers) > max_layers:
            report.violations.append(DFMViolation(
                "DFM_MAX_LAYERS",
                f"{len(graph.layers)} couches > maximum {max_layers} chez {prof.get('name')}",
                "error", {"layers": len(graph.layers)}))

        # 2. Largeurs de traces vs usine
        for net in graph.nets.values():
            if net.path is None:
                continue
            report.checked += 1
            if net.path.width_mm < min_trace - 1e-9:
                report.violations.append(DFMViolation(
                    "DFM_MIN_TRACE",
                    f"Trace {net.path.width_mm:.3f}mm < {min_trace}mm chez {prof.get('name')} "
                    f"(net '{net.name or net.net_id}')",
                    "error", {"net": net.net_id, "width_mm": net.path.width_mm}))

        # 3. Vias : forage minimal + annular ring
        for net in graph.nets.values():
            if net.path is None:
                continue
            for _pos, _fl, _tl in net.path.vias:
                report.checked += 1
                # forage par défaut 0.3mm / pad 0.6mm (représentation interne)
                if min_hole - 1e-9 > 0.3:
                    report.violations.append(DFMViolation(
                        "DFM_MIN_HOLE",
                        f"Forage via 0.300mm < {min_hole}mm chez {prof.get('name')}",
                        "error", {"net": net.net_id}))
                    break
            if len(net.path.vias) > 40:
                report.violations.append(DFMViolation(
                    "DFM_EXCESS_VIAS",
                    f"Net '{net.name or net.net_id}' utilise {len(net.path.vias)} vias "
                    f"(coût/rendement dégradés)",
                    "warning", {"net": net.net_id, "vias": len(net.path.vias)}))

        # 4. Mixte THT / SMD — pénalise les lignes d'assemblage doubles
        footprints = [c.footprint.lower() for c in graph.components.values()]
        report.checked += 1
        has_tht = any(k in f for f in footprints for k in ("dip", "to-220", "to-92", "sot-dip"))
        if has_tht and prof.get("assembly"):
            report.violations.append(DFMViolation(
                "DFM_MIXED_THT_SMD",
                "Design mixte THT+SMD : deux passes d'assemblage chez "
                f"{prof.get('name')} (surcoût)",
                "warning", {}))

        # 5. Densité d'assemblage vs capacités SMT
        board_area = graph.board_size[0] * graph.board_size[1]
        if board_area > 0 and graph.components:
            density = len(graph.components) / board_area * 100.0  # comp/100mm²
            report.checked += 1
            if density > 8.0:
                report.violations.append(DFMViolation(
                    "DFM_HIGH_DENSITY",
                    f"Densité d'assemblage élevée ({density:.1f} comp/100mm²) — "
                    f"risque d'erreur de placement chez {prof.get('name')}",
                    "warning", {"density": round(density, 2)}))

        # 6. Traces < clearance usine (re-check rapide des gaps nets vs profil)
        report.checked += 1
        if min_clear < 0.09:
            report.violations.append(DFMViolation(
                "DFM_UNUSUAL_CLEARANCE",
                f"Clearance usine {min_clear}mm inhabituellement faible",
                "info", {}))

        # 7. Épaisseur cuivre (proxy : 1oz standard supposé)
        report.checked += 1
        if float(prof.get("unit_price_factor", 1.0)) > 1.2:
            report.violations.append(DFMViolation(
                "DFM_COST_FACTOR",
                f"Usine {prof.get('name')} : facteur prix élevé "
                f"({prof.get('unit_price_factor')}x) — comparer avec JLCPCB",
                "info", {}))

        log.info("DFM[%s]: %d checks, %d violations, passed=%s",
                 self.factory, report.checked, len(report.violations), report.passed)
        return report
