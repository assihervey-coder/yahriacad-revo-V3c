"""manufacturing_intelligence — profils usine, devis, coût, yield, feedback DFM."""
from typing import Any

from shared.utilities import get_logger

from services.manufacturing_intelligence.cost_estimator import CostBreakdown, CostEstimator
from services.manufacturing_intelligence.factory_profiles import (
    DEFAULTS,
    FactoryProfile,
    get_profile,
    list_profiles,
    profile_dict,
)
from services.manufacturing_intelligence.jlcpcb import JLCPCBClient
from services.manufacturing_intelligence.manufacturing_feedback import (
    ManufacturingFeedback,
    ProfileAdjustment,
)
from services.manufacturing_intelligence.pcbway import PCBWayClient, Quote
from services.manufacturing_intelligence.yield_predictor import YieldPrediction, YieldPredictor

__all__ = [
    "DEFAULTS",
    "CostBreakdown",
    "CostEstimator",
    "FactoryProfile",
    "JLCPCBClient",
    "ManufacturingFeedback",
    "PCBWayClient",
    "ProfileAdjustment",
    "Quote",
    "ManufacturingIntelligence",
    "YieldPredictor",
    "YieldPrediction",
    "analyze",
    "get_profile",
    "list_profiles",
    "profile_dict",
]

log = get_logger(__name__)


def _mini_dfm_report(graph: Any, profile: FactoryProfile) -> dict[str, Any]:
    """Mini-check DFM interne (traces/vias) pour alimenter la boucle de feedback."""
    violations: list = []
    for net in graph.nets.values():
        path = getattr(net, "path", None)
        if path is None or not getattr(path, "points", []):
            continue
        width = float(getattr(path, "width_mm", 0.2))
        if width < profile.min_trace_mm:
            violations.append({
                "constraint_id": f"dfm.min_trace[{getattr(net, 'net_id', '')}]",
                "severity": "error",
                "message": f"trace {width} mm < min usine {profile.min_trace_mm} mm",
            })
    return {"violations": violations}


class ManufacturingIntelligence:
    """Façade d'analyse manufacturière complète (profil + coût + yield + feedback)."""

    def __init__(self, factory: str = "jlcpcb") -> None:
        self.factory = factory

    def analyze(self, graph: Any, factory: str = "") -> dict[str, Any]:
        """Analyse complète : profile, cost, yield, suggestions, feedback DFM."""
        profile = get_profile(factory or self.factory)
        cost = CostEstimator(profile).estimate(graph)
        yield_pred = YieldPredictor().predict(graph, profile)
        suggestions = CostEstimator(profile).optimize_for_cost(graph)
        feedback = ManufacturingFeedback().feedback_loop(
            _mini_dfm_report(graph, profile),
            rules={"min_trace_mm": profile.min_trace_mm,
                   "min_clearance_mm": profile.min_clearance_mm,
                   "min_hole_mm": profile.min_hole_mm,
                   "min_annular_ring_mm": profile.min_annular_ring_mm,
                   "max_layers": profile.max_layers},
            project_id=str(getattr(graph, "project_id", "")),
        )
        client = JLCPCBClient() if profile.name == "jlcpcb" else PCBWayClient()
        quote = client.quote({
            "width_mm": graph.board_size[0],
            "height_mm": graph.board_size[1],
            "layers": len(list(getattr(graph, "layers", []) or [])),
            "quantity": 1,
            "min_trace_mm": profile.min_trace_mm,
            "lead_time_days": profile.lead_time_days,
        })
        mpns = sorted({str(getattr(c, "mpn", "") or "") for c in graph.components.values()}
                      - {""})
        availability = (client.check_part_availability(mpns)
                        if isinstance(client, JLCPCBClient) and mpns else {})
        report = {
            "factory": profile.name,
            "profile": profile_dict(profile),
            "cost": {
                "board_usd": cost.board_usd,
                "assembly_usd": cost.assembly_usd,
                "components_usd": cost.components_usd,
                "total_usd": cost.total_usd,
                "details": cost.details,
            },
            "quote": {
                "base_usd": quote.base_usd,
                "shipping_usd": quote.shipping_usd,
                "total_usd": quote.total_usd,
                "lead_time_days": quote.lead_time,
                "source": quote.source,
            },
            "yield": {
                "expected_yield": yield_pred.expected_yield,
                "risk_factors": yield_pred.risk_factors,
                "model": yield_pred.model,
            },
            "cost_suggestions": suggestions,
            "dfm_feedback": feedback,
            "part_availability": availability,
        }
        log.info("analyse manufacturière %s: total %.2f$, yield %.1f%%",
                 profile.name, cost.total_usd, 100 * yield_pred.expected_yield)
        return report


def analyze(graph: Any, factory: str = "jlcpcb") -> dict[str, Any]:
    """Raccourci module-level : ManufacturingIntelligence(factory).analyze(graph)."""
    return ManufacturingIntelligence(factory).analyze(graph)
