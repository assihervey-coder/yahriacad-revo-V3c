"""Base des simulations multi-physique — contrat SimResult / BaseSim."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from services.design_core import DesignGraph


@dataclass
class SimResult:
    """Résultat normalisé d'une simulation (tous les moteurs y adhèrent)."""

    sim_kind: str                    # "thermal" | "emi" | "si" | "pi" | "mechanical"
    metrics: dict[str, Any]
    passed: bool
    runtime_s: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_kind": self.sim_kind,
            "metrics": self.metrics,
            "passed": self.passed,
            "runtime_s": round(self.runtime_s, 4),
            "notes": self.notes,
        }


class BaseSim:
    """Contrat commun : chaque simulateur implémente run(graph) -> SimResult."""

    sim_kind: str = "base"

    def run(self, graph: DesignGraph) -> SimResult:
        raise NotImplementedError

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _timed(metrics: dict[str, Any], passed: bool, notes: list[str],
               t0: float) -> SimResult:
        return SimResult(sim_kind="?", metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} sim_kind={self.sim_kind}>"
