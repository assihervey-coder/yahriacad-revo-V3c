"""Contraintes mécaniques : clearances, outline carte, keepouts, densité."""
from __future__ import annotations

from itertools import combinations
from typing import List

from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.design_graph.geometry import (
    bbox_area,
    bbox_gap_mm,
    component_bbox_mm,
)
from services.design_core.design_graph.graph import DesignGraph


class MinClearance(BaseConstraint):
    """Distance minimale entre composants placés (bbox vs bbox)."""

    def __init__(self, min_clearance_mm: float = 0.2) -> None:
        super().__init__(
            "min_clearance", "mechanical", "error",
            f"clearance inter-composants >= {min_clearance_mm} mm",
        )
        self.min_clearance_mm = min_clearance_mm

    def check(self, graph: DesignGraph) -> List[Violation]:
        placed = graph.placed_components()
        violations: List[Violation] = []
        for a, b in combinations(placed, 2):
            gap = bbox_gap_mm(component_bbox_mm(a), component_bbox_mm(b))
            if gap < self.min_clearance_mm:
                violations.append(self.violation(
                    f"clearance {a.ref}/{b.ref} = {gap:.3f} mm < {self.min_clearance_mm} mm",
                    location={"a": a.ref, "b": b.ref, "gap_mm": round(gap, 4)},
                ))
        return violations


class BoardOutline(BaseConstraint):
    """Composants placés sortant des dimensions de la carte."""

    def __init__(self, margin_mm: float = 0.0) -> None:
        super().__init__(
            "board_outline", "mechanical", "error",
            "tout composant doit tenir dans le contour carte",
        )
        self.margin_mm = margin_mm

    def check(self, graph: DesignGraph) -> List[Violation]:
        w, h = graph.board_size
        violations: List[Violation] = []
        for comp in graph.placed_components():
            x0, y0, x1, y1 = component_bbox_mm(comp)
            if x0 < -self.margin_mm or y0 < -self.margin_mm or x1 > w + self.margin_mm or y1 > h + self.margin_mm:
                violations.append(self.violation(
                    f"{comp.ref} hors contour carte "
                    f"(bbox [{x0:.1f}, {y0:.1f}] -> [{x1:.1f}, {y1:.1f}], board {w}x{h} mm)",
                    location={"ref": comp.ref, "bbox_mm": [x0, y0, x1, y1]},
                ))
        return violations


class KeepoutViolation(BaseConstraint):
    """Composant placé empiétant sur une zone interdite."""

    def __init__(self) -> None:
        super().__init__(
            "keepout_violation", "mechanical", "error",
            "aucun composant ne doit entrer dans un keepout",
        )

    def check(self, graph: DesignGraph) -> List[Violation]:
        violations: List[Violation] = []
        for comp in graph.placed_components():
            for keepout in graph.violates_keepouts(comp.x, comp.y, *comp.bbox):
                violations.append(self.violation(
                    f"{comp.ref} entre dans le keepout '{keepout.name}'",
                    location={"ref": comp.ref, "keepout": keepout.name},
                ))
        return violations


class MaxBoardUtilization(BaseConstraint):
    """Densité d'occupation de la carte au-dessus du seuil (défaut 85 %)."""

    def __init__(self, max_utilization: float = 0.85) -> None:
        super().__init__(
            "max_board_utilization", "mechanical", "warning",
            f"densité d'occupation carte <= {max_utilization:.0%}",
        )
        self.max_utilization = max_utilization

    def check(self, graph: DesignGraph) -> List[Violation]:
        utilization = graph.utilization()
        if utilization > self.max_utilization:
            board_area = graph.board_size[0] * graph.board_size[1]
            used = sum(bbox_area(component_bbox_mm(c)) for c in graph.placed_components())
            return [self.violation(
                f"densité carte {utilization:.1%} > {self.max_utilization:.0%} "
                f"({used:.0f} mm² / {board_area:.0f} mm²)",
                location={"utilization": round(utilization, 4)},
            )]
        return []
