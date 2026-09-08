"""Contraintes de coût : budget composants (BOM) maximum."""
from __future__ import annotations

from typing import List

from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.design_graph.graph import DesignGraph


class MaxCostUSD(BaseConstraint):
    """Coût total composants du BOM au-delà du budget autorisé."""

    def __init__(self, max_usd: float = 50.0) -> None:
        super().__init__(
            "max_cost_usd", "cost", "error",
            f"coût BOM <= {max_usd:.2f} $",
        )
        self.max_usd = max_usd

    def check(self, graph: DesignGraph) -> List[Violation]:
        cost = graph.cost_usd()
        if cost > self.max_usd:
            top = sorted(graph.components.values(), key=lambda c: -c.price_usd)[:3]
            return [self.violation(
                f"coût BOM {cost:.2f} $ > budget {self.max_usd:.2f} $ "
                f"(top: {', '.join(f'{c.ref}={c.price_usd:.2f}$' for c in top)})",
                location={"cost_usd": round(cost, 2), "max_usd": self.max_usd},
            )]
        return []
