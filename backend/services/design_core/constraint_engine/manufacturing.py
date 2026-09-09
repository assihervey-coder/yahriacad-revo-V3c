"""Contraintes de fabrication : limites d'assemblage (nombre de composants)."""
from __future__ import annotations

from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.design_graph.graph import DesignGraph


class MaxComponentCount(BaseConstraint):
    """Nombre de composants au-delà des limites raisonnables d'assemblage.

    Référence : lignes d'assemblage JLCPCB/PCBWay (limite économique ~500 pads
    et composants unique-part par panneau) — au-delà, coût et rendement chutent.
    """

    def __init__(self, max_components: int = 500) -> None:
        super().__init__(
            "max_component_count", "manufacturing", "error",
            f"nombre de composants <= {max_components}",
        )
        self.max_components = max_components

    def check(self, graph: DesignGraph) -> list[Violation]:
        count = len(graph.components)
        if count > self.max_components:
            return [self.violation(
                f"{count} composants > limite {self.max_components} (assemblage)",
                location={"count": count, "max": self.max_components},
            )]
        return []
