"""Contraintes électriques : largeur de piste, impédance, paires diff, découplage."""
from __future__ import annotations

from typing import Dict, List, Optional

from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.design_graph.geometry import bbox_gap_mm, component_bbox_mm
from services.design_core.design_graph.graph import DesignGraph

# Largeur de piste par défaut (mm) selon la classe de net — proxy sans impédance.
DEFAULT_CLASS_WIDTH_MM: Dict[str, float] = {
    "default": 0.25,
    "power": 0.5,
    "analog": 0.2,
    "high_speed": 0.2,
    "differential": 0.2,
}


class MinTraceWidth(BaseConstraint):
    """Largeur de piste minimale (proxy : classe de net, ou RoutePath existant)."""

    def __init__(self, min_width_mm: float = 0.2) -> None:
        super().__init__(
            "min_trace_width", "electrical", "warning",
            f"largeur de piste >= {min_width_mm} mm",
        )
        self.min_width_mm = min_width_mm

    def check(self, graph: DesignGraph) -> List[Violation]:
        violations: List[Violation] = []
        for net in graph.nets.values():
            width = (
                net.path.width_mm if net.path is not None
                else DEFAULT_CLASS_WIDTH_MM.get(net.class_name, 0.25)
            )
            if width < self.min_width_mm:
                violations.append(self.violation(
                    f"net '{net.net_id}' (classe {net.class_name}) largeur {width:.3f} mm "
                    f"< {self.min_width_mm} mm",
                    location={"net_id": net.net_id, "width_mm": width},
                ))
        return violations


class ImpedanceTarget(BaseConstraint):
    """Nets haut débit / différentiels sans cible d'impédance (ou hors tolérance)."""

    def __init__(self, required_ohm: Optional[float] = None, tolerance: float = 0.05) -> None:
        super().__init__(
            "impedance_target", "electrical", "warning",
            "les nets high_speed/differential doivent viser une impédance contrôlée",
        )
        self.required_ohm = required_ohm
        self.tolerance = tolerance

    def check(self, graph: DesignGraph) -> List[Violation]:
        violations: List[Violation] = []
        for net in graph.nets.values():
            if net.class_name not in ("high_speed", "differential"):
                continue
            if net.impedance_target_ohm is None:
                violations.append(self.violation(
                    f"net '{net.net_id}' (classe {net.class_name}) sans impedance_target_ohm",
                    location={"net_id": net.net_id},
                ))
            elif self.required_ohm is not None:
                target = net.impedance_target_ohm
                if abs(target - self.required_ohm) / self.required_ohm > self.tolerance:
                    violations.append(self.violation(
                        f"net '{net.net_id}' impédance {target} Ω ≠ {self.required_ohm} Ω requis "
                        f"(±{self.tolerance:.0%})",
                        location={"net_id": net.net_id, "target_ohm": target},
                    ))
        return violations


class DifferentialPairSymmetry(BaseConstraint):
    """Nets appariés (matched_group) avec longueurs max incohérentes."""

    def __init__(self, tolerance_mm: float = 0.1) -> None:
        super().__init__(
            "diff_pair_symmetry", "electrical", "warning",
            "les nets d'un même matched_group doivent partager la même longueur max",
        )
        self.tolerance_mm = tolerance_mm

    def check(self, graph: DesignGraph) -> List[Violation]:
        groups: Dict[str, List[float]] = {}
        for net in graph.nets.values():
            if net.matched_group and net.max_length_mm is not None:
                groups.setdefault(net.matched_group, []).append(net.max_length_mm)
        violations: List[Violation] = []
        for group, lengths in groups.items():
            if len(lengths) > 1 and (max(lengths) - min(lengths)) > self.tolerance_mm:
                violations.append(self.violation(
                    f"groupe apparié '{group}' : max_length_mm disparate "
                    f"({min(lengths)} .. {max(lengths)} mm)",
                    location={"matched_group": group, "lengths_mm": lengths},
                ))
        return violations


class DecouplingCapProximity(BaseConstraint):
    """Composant de puissance sans cap de découplage à moins de max_distance_mm."""

    def __init__(self, max_distance_mm: float = 5.0, power_threshold_w: float = 0.05) -> None:
        super().__init__(
            "decoupling_cap_proximity", "electrical", "warning",
            f"un condensateur de découplage doit être à <= {max_distance_mm} mm "
            f"de tout composant dissipant >= {power_threshold_w} W",
        )
        self.max_distance_mm = max_distance_mm
        self.power_threshold_w = power_threshold_w

    @staticmethod
    def _is_cap(ref: str) -> bool:
        """Proxy standard : les condensateurs sont référencés 'C...'."""
        return ref.upper().startswith("C")

    def check(self, graph: DesignGraph) -> List[Violation]:
        placed = graph.placed_components()
        caps = [c for c in placed if self._is_cap(c.ref)]
        violations: List[Violation] = []
        for comp in placed:
            if comp.power_w < self.power_threshold_w or self._is_cap(comp.ref):
                continue
            if not caps:
                violations.append(self.violation(
                    f"{comp.ref} ({comp.power_w:.2f} W) sans condensateur de découplage dans le design",
                    location={"ref": comp.ref},
                ))
                continue
            nearest = min(caps, key=lambda c: bbox_gap_mm(component_bbox_mm(comp), component_bbox_mm(c)))
            gap = bbox_gap_mm(component_bbox_mm(comp), component_bbox_mm(nearest))
            if gap > self.max_distance_mm:
                violations.append(self.violation(
                    f"{comp.ref} ({comp.power_w:.2f} W) : découplage le plus proche {nearest.ref} "
                    f"à {gap:.1f} mm > {self.max_distance_mm} mm",
                    location={"ref": comp.ref, "nearest_cap": nearest.ref, "gap_mm": round(gap, 2)},
                ))
        return violations
