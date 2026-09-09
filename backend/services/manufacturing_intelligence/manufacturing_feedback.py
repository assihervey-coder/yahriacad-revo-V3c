"""Boucle de retour manufacturier — DFM → ajustements de règles → constraint_bus."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

from services.integration_utils import make_and_publish

log = get_logger(__name__)

FEEDBACK_EVENT = "manufacturing.feedback"

# mot-clé dans l'identifiant de violation → règle de profil impactée
_RULE_MAP = {
    "trace": "min_trace_mm",
    "width": "min_trace_mm",
    "clearance": "min_clearance_mm",
    "spacing": "min_clearance_mm",
    "hole": "min_hole_mm",
    "drill": "min_hole_mm",
    "annular": "min_annular_ring_mm",
}
_SEVERITY_FACTOR = {"critical": 2.0, "error": 2.0, "warning": 1.0, "info": 0.5}


@dataclass
class ProfileAdjustment:
    """Ajustement proposé pour une contrainte/une règle de profil."""

    constraint_id: str
    adjustment: dict[str, float] = field(default_factory=dict)


def _violations(dfm_report: Any) -> list[dict[str, Any]]:
    """Extrait la liste des violations (dict {violations: [...]} ou liste brute)."""
    if isinstance(dfm_report, dict):
        for key in ("violations", "issues", "dfm_violations"):
            if isinstance(dfm_report.get(key), list):
                return dfm_report[key]
        return []
    if isinstance(dfm_report, list):
        return dfm_report
    return []


class ManufacturingFeedback:
    """Transforme un rapport DFM en ajustements de règles, puis boucle l'event."""

    def from_dfm_report(self, dfm_report: Any) -> list[ProfileAdjustment]:
        """Rapport DFM → ajustements de contraintes (marges resserrées/élargies)."""
        adjustments: list[ProfileAdjustment] = []
        for v in _violations(dfm_report):
            if not isinstance(v, dict):
                continue
            cid = str(v.get("constraint_id") or v.get("rule") or v.get("code") or "")
            low = cid.lower()
            factor = _SEVERITY_FACTOR.get(str(v.get("severity", "warning")).lower(), 1.0)
            rule = next((r for key, r in _RULE_MAP.items() if key in low), None)
            if rule is None:
                continue
            # on ajoute une marge de sécurité proportionnelle à la sévérité
            delta = round(0.05 * factor, 4)
            adjustments.append(ProfileAdjustment(
                constraint_id=cid, adjustment={rule: delta}))
        log.info("feedback DFM: %d ajustement(s) proposé(s)", len(adjustments))
        return adjustments

    def apply_to_rules(self, rules: dict[str, Any],
                       adjustments: list[ProfileAdjustment]) -> dict[str, Any]:
        """Resserre les règles : min_* montent, max_* descendent (jamais d'assouplissement)."""
        out = dict(rules)
        for adj in adjustments:
            for key, delta in adj.adjustment.items():
                current = out.get(key)
                if key.startswith("min_"):
                    if isinstance(current, (int, float)):
                        out[key] = max(float(current), float(current) + delta)
                    else:
                        out[key] = delta
                elif key.startswith("max_"):
                    if isinstance(current, (int, float)) and current > 2:
                        out[key] = max(2, int(current) - 1)  # réduire la capacité permise
                    else:
                        out[key] = current
                else:
                    out[key] = delta
        return out

    def feedback_loop(self, dfm_report: Any, rules: dict[str, Any],
                      project_id: str = "") -> dict[str, Any]:
        """Passe complète : ajustements → règles resserrées → event constraint_bus."""
        adjustments = self.from_dfm_report(dfm_report)
        new_rules = self.apply_to_rules(rules, adjustments)
        published = make_and_publish(
            FEEDBACK_EVENT,
            {"adjustments": [vars(a) for a in adjustments],
             "rules": new_rules,
             "violations": len(_violations(dfm_report))},
            project_id=project_id,
            source="manufacturing_intelligence",
        )
        if not published:
            log.debug("event %s non publié (pas de boucle async)", FEEDBACK_EVENT)
        return new_rules
