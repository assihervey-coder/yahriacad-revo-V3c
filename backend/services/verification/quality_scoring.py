"""Scoring qualité global — agrège toutes les dimensions en une note 0..100."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

from services.design_core.design_graph.graph import DesignGraph

log = get_logger(__name__)

# pondérations des sous-scores (somme = 1.0)
WEIGHTS = {
    "erc": 0.18,
    "drc": 0.18,
    "dfm": 0.14,
    "routing_completeness": 0.16,
    "thermal": 0.12,
    "signal_integrity": 0.12,
    "cost_efficiency": 0.10,
}


@dataclass
class QualityScore:
    total: float = 0.0
    breakdown: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"total": round(self.total, 1),
                "breakdown": {k: round(v, 1) for k, v in self.breakdown.items()},
                "notes": self.notes}


class QualityScorer:
    """Note qualité 0..100 du design, toutes dimensions confondues.

    `reports` attend des clés optionnelles : erc, drc, dfm (rapports .to_dict()),
    sim_results (dict sim_kind -> SimResult.to_dict()).
    """

    def score(self, graph: DesignGraph, reports: dict[str, Any] | None = None) -> QualityScore:
        reports = reports or {}
        breakdown: dict[str, float] = {}
        notes: list[str] = []

        # ERC / DRC / DFM : score des rapports (0..1 → 0..100)
        for key in ("erc", "drc", "dfm"):
            rep = reports.get(key)
            if rep and isinstance(rep, dict):
                breakdown[key] = float(rep.get("score", 0.0)) * 100.0
                if not rep.get("passed", True):
                    notes.append(f"{key.upper()} : violations présentes")
            else:
                breakdown[key] = 50.0  # non vérifié → neutre

        # Complétude du routage
        nets = list(graph.nets.values())
        routed = sum(1 for n in nets if n.routed)
        breakdown["routing_completeness"] = (routed / len(nets) * 100.0) if nets else 100.0
        if nets and routed < len(nets):
            notes.append(f"{len(nets) - routed} net(s) non routé(s)")

        # Thermique (depuis sim_results si fourni)
        thermal = reports.get("sim_results", {}).get("thermal", {})
        if thermal:
            metrics = thermal.get("metrics", {})
            max_temp = float(metrics.get("max_temp_c", 25.0))
            # 25°C → 100, 85°C → 0
            breakdown["thermal"] = max(0.0, min(100.0, (85.0 - max_temp) / (85.0 - 25.0) * 100.0))
            if max_temp > 85.0:
                notes.append(f"Thermique : hotspot à {max_temp:.0f}°C")
        else:
            breakdown["thermal"] = 60.0  # non simulé

        # Signal integrity
        si = reports.get("sim_results", {}).get("signal_integrity", {})
        if si:
            passed_ratio = 1.0 if si.get("passed", True) else 0.5
            breakdown["signal_integrity"] = passed_ratio * 100.0
        else:
            breakdown["signal_integrity"] = 60.0

        # Efficacité coût (proxy : coût passifs vs budget 50$)
        cost = graph.cost_usd()
        breakdown["cost_efficiency"] = max(0.0, min(100.0, 100.0 - cost * 2.0))

        total = sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS)
        qs = QualityScore(total=total, breakdown=breakdown, notes=notes)
        log.info("Qualité: %.1f/100 %s", qs.total, {k: round(v) for k, v in breakdown.items()})
        return qs
