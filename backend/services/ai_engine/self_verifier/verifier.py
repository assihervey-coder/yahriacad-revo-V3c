"""SelfVerifier — orchestre les checks et émet les events de vérification."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.utilities import get_logger, new_id
from shared.events import EventTypes, make_event
from services.ai_engine._event_helpers import publish_nowait
from services.ai_engine.self_verifier.confidence import ConfidenceScorer
from services.ai_engine.self_verifier.deterministic import check_deterministic
from services.ai_engine.self_verifier.physical import check_physical

log = get_logger("ai_engine.verify.verifier")


@dataclass
class VerificationReport:
    """Rapport de vérification consolidé."""

    passed: bool
    issues: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    checked_by: List[str] = field(default_factory=list)
    report_id: str = field(default_factory=lambda: new_id("ver"))

    def to_dict(self) -> Dict[str, Any]:
        """Sérialisation."""
        return {
            "report_id": self.report_id, "passed": self.passed,
            "confidence": self.confidence, "checked_by": self.checked_by,
            "issues": self.issues,
        }


class SelfVerifier:
    """Vérificateur autonome : déterministe + physique + confiance.

    passed = aucun issue "error" ET confidence ≥ 0.6.
    Émet VERIFICATION_PASSED / VERIFICATION_FAILED sur l'event bus.
    """

    MIN_CONFIDENCE = 0.6

    def __init__(self, versioning=None,  # noqa: ANN001 — DesignVersioning|None
                 scorer: Optional[ConfidenceScorer] = None,
                 emit_events: bool = True) -> None:
        self.versioning = versioning
        self.scorer = scorer or ConfidenceScorer()
        self.emit_events = emit_events

    def verify(self, graph,  # noqa: ANN001 — DesignGraph
               context: Optional[Dict[str, Any]] = None,
               quick: bool = True) -> VerificationReport:
        """Vérifie un graphe et retourne un rapport + event bus."""
        context = context or {}
        issues: List[Dict[str, Any]] = []
        checked_by: List[str] = []

        issues.extend(check_deterministic(graph))
        checked_by.append("deterministic")

        if context.get("skip_physical"):
            checked_by.append("physical:skipped")
        else:
            issues.extend(check_physical(graph, quick=quick))
            checked_by.append("physical")

        # engine de contraintes externe (optionnel, duck-typed)
        engine = context.get("constraint_engine")
        if engine is not None:
            try:
                ext = engine.check(graph)
                if isinstance(ext, list):
                    issues.extend(ext)
                checked_by.append("constraint_engine")
            except Exception as exc:
                log.warning("constraint_engine.check échoué: %s", exc)

        confidence = self.scorer.score(graph, issues)
        has_error = any(str(i.get("severity", "")).lower() == "error"
                        for i in issues)
        passed = (not has_error) and confidence >= self.MIN_CONFIDENCE

        report = VerificationReport(passed=passed, issues=issues,
                                    confidence=confidence, checked_by=checked_by)
        self._emit(passed, report, context)
        log.info("vérification: passed=%s confidence=%.3f issues=%d",
                 passed, confidence, len(issues))
        return report

    # ------------------------------------------------------------- events
    def _emit(self, passed: bool, report: VerificationReport,
              context: Dict[str, Any]) -> None:
        if not self.emit_events:
            return
        try:
            event = make_event(
                EventTypes.VERIFICATION_PASSED if passed
                else EventTypes.VERIFICATION_FAILED,
                payload={
                    "report_id": report.report_id,
                    "confidence": report.confidence,
                    "n_issues": len(report.issues),
                    "errors": [i for i in report.issues
                               if str(i.get("severity")) == "error"][:10],
                },
                project_id=str(context.get("project_id", "")),
                correlation_id=str(context.get("correlation_id", "")),
                source="ai_engine.self_verifier",
            )
            publish_nowait(event)
        except Exception as exc:  # le bus ne doit jamais casser la vérification
            log.warning("émission event vérification échouée: %s", exc)
