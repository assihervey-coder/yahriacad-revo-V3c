"""Contraintes thermiques : hotspots de densité de puissance locale."""
from __future__ import annotations

from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.design_graph.graph import DesignGraph


class ThermalHotspot(BaseConstraint):
    """Densité de puissance locale > seuil (W/mm²) sur une grille de cell_mm.

    Proxy rapide utilisé avant la simulation thermique complète : chaque
    composant placé cumule sa puissance dans la cellule de grille qui le
    contient ; une cellule au-dessus du seuil est un hotspot potentiel.
    """

    def __init__(self, threshold_w_per_mm2: float = 0.01, cell_mm: float = 10.0) -> None:
        super().__init__(
            "thermal_hotspot", "thermal", "error",
            f"densité de puissance locale <= {threshold_w_per_mm2} W/mm² "
            f"(grille {cell_mm} mm)",
        )
        self.threshold_w_per_mm2 = threshold_w_per_mm2
        self.cell_mm = cell_mm

    def check(self, graph: DesignGraph) -> list[Violation]:
        cell = max(0.1, self.cell_mm)
        cells: dict[tuple[int, int], float] = {}
        for comp in graph.placed_components():
            key = (int(comp.x // cell), int(comp.y // cell))
            cells[key] = cells.get(key, 0.0) + comp.power_w
        cell_area = cell * cell
        violations: list[Violation] = []
        for (cx, cy), power in cells.items():
            density = power / cell_area
            if density > self.threshold_w_per_mm2:
                violations.append(self.violation(
                    f"hotspot {density:.4f} W/mm² > {self.threshold_w_per_mm2} W/mm² "
                    f"autour de ({cx * cell + cell / 2:.0f}, {cy * cell + cell / 2:.0f}) mm "
                    f"({power:.2f} W cumulés)",
                    location={"cell": [cx, cy], "power_w": round(power, 4),
                              "density_w_per_mm2": round(density, 5)},
                ))
        return violations
