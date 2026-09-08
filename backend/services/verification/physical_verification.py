"""Vérification physique globale : ERC + DRC + DFM orchestrés."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from shared.utilities import get_logger
from services.design_core.design_graph.graph import DesignGraph
from services.verification.design_rules import DesignRules
from services.verification.drc_engine import DRCEngine
from services.verification.erc_engine import ERCEngine
from services.verification.dfm_engine import DFMEngine

log = get_logger(__name__)


@dataclass
class PhysicalVerificationReport:
    erc: Dict[str, Any] = field(default_factory=dict)
    drc: Dict[str, Any] = field(default_factory=dict)
    dfm: Dict[str, Any] = field(default_factory=dict)
    passed: bool = False
    duration_ms: float = 0.0

    @property
    def total_violations(self) -> int:
        n = 0
        for section in (self.erc, self.drc, self.dfm):
            n += len(section.get("violations", []))
        return n

    def to_dict(self) -> Dict[str, Any]:
        return {
            "erc": self.erc, "drc": self.drc, "dfm": self.dfm,
            "passed": self.passed, "duration_ms": round(self.duration_ms, 1),
            "total_violations": self.total_violations,
        }


class PhysicalVerification:
    """Point d'entrée unique du cerveau physique de vérification.

    Utilisé par : validator_agent, self_verifier, api, human surgical editor.
    """

    def __init__(self, rules: Optional[DesignRules] = None, factory: str = "jlcpcb") -> None:
        self.rules = rules
        self.factory = factory

    def run_all(self, graph: DesignGraph, factory: Optional[str] = None) -> PhysicalVerificationReport:
        t0 = time.perf_counter()
        factory = factory or self.factory
        erc_report = ERCEngine().run(graph)
        drc_report = DRCEngine(self.rules).run(graph)
        dfm_report = DFMEngine(factory=factory).run(graph)
        report = PhysicalVerificationReport(
            erc=erc_report.to_dict(),
            drc=drc_report.to_dict(),
            dfm=dfm_report.to_dict(),
            passed=erc_report.passed and drc_report.passed and dfm_report.passed,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )
        log.info("Verification physique: passed=%s violations=%d (%.0fms)",
                 report.passed, report.total_violations, report.duration_ms)
        return report
