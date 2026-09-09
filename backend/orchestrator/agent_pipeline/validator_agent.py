"""ValidatorAgent — vérification complète (self + physique + qualité)."""
from __future__ import annotations

from typing import Any

from shared.contracts import AgentRole
from shared.events import EventTypes
from shared.schemas import AgentResultSchema

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.validator_checks import local_checks
from orchestrator.common import (
    call_probe,
    get_field,
    try_import,
)


class ValidatorAgent(BaseAgent):
    """Étape `verify` : SelfVerifier + PhysicalVerification + QualityScorer.

    Suggère des corrections si la vérification échoue (consommées par le
    CorrectorAgent).
    """

    role = AgentRole.VALIDATOR
    description = "Vérifie le design (auto-cohérence, DRC/ERC/DFM) et score la qualité."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.VALIDATOR, "validator", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("verify_all", "verify", "")

    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")
        params = context.get("params") or {}
        factory = params.get("factory")

        verification: dict[str, Any] = {}
        reports: list[Any] = []

        # 1) Self-verifier du cerveau IA
        self_mod = try_import("services.ai_engine", ["SelfVerifier"])
        self_cls = self_mod.get("SelfVerifier")
        if self_cls is not None:
            try:
                try:
                    verifier = self_cls()
                except TypeError:
                    verifier = self_cls(self.orchestrator)
                report = verifier.verify(graph, context)
                reports.append(report)
                verification["self"] = {
                    "passed": bool(get_field(report, "passed", "ok", default=True)),
                    "issues": _stringify_issues(get_field(report, "issues", default=[])),
                    "confidence": float(get_field(report, "confidence", default=0.8) or 0.8),
                }
            except Exception as exc:
                self.log.debug("SelfVerifier indisponible: %s", exc)

        # 2) Vérification physique (DRC/ERC/DFM)
        phys_mod = try_import("services.verification", ["PhysicalVerification"])
        phys_cls = phys_mod.get("PhysicalVerification")
        if phys_cls is not None:
            try:
                try:
                    pv = phys_cls()
                except TypeError:
                    pv = phys_cls()
                report = call_probe(pv, "run_all", (graph, factory), (graph,))
                reports.append(report)
                verification["physical"] = {
                    "passed": bool(get_field(report, "passed", "ok", default=True)),
                    "issues": _stringify_issues(get_field(report, "issues", "violations", default=[])),
                    "report": _summary(report),
                }
            except Exception as exc:
                self.log.debug("PhysicalVerification indisponible: %s", exc)

        # 3) Score qualité
        quality_mod = try_import("services.verification", ["QualityScorer"])
        scorer_cls = quality_mod.get("QualityScorer")
        if scorer_cls is not None and reports:
            try:
                try:
                    scorer = scorer_cls()
                except TypeError:
                    scorer = scorer_cls()
                score = scorer.score(graph, reports)
                verification["quality"] = {
                    "total": float(get_field(score, "total", default=0.0) or 0.0),
                    "breakdown": _jsonable(get_field(score, "breakdown", default={})),
                }
            except Exception as exc:
                self.log.debug("QualityScorer indisponible: %s", exc)

        # 4) Contrôles locaux de repli (toujours exécutés, enrichissent le rapport)
        local = local_checks(graph)
        verification["local"] = local
        if "self" not in verification:
            verification["self"] = {"passed": local["passed"],
                                    "issues": local["issues"],
                                    "confidence": 0.6}
            reports.append(local)

        passed_flags = [verification[key]["passed"]
                        for key in ("self", "physical") if key in verification]
        all_passed = all(passed_flags) if passed_flags else local["passed"]
        quality_total = float(verification.get("quality", {}).get("total", local.get("quality", 60.0)))

        suggestions = self._suggestions(verification)
        verification["passed"] = all_passed
        verification["suggestions"] = suggestions
        context["verification"] = verification

        self.record_decision(context, "verification",
                             f"{'PASS' if all_passed else 'FAIL'} — qualité {quality_total:.1f}/100",
                             confidence=0.9 if all_passed else 0.4)
        self.emit(EventTypes.VERIFICATION_PASSED if all_passed else EventTypes.VERIFICATION_FAILED,
                  {"quality": quality_total, "suggestions": suggestions[:5]}, context)
        output = {"verification": verification, "passed": all_passed, "suggestions": suggestions}
        return self.succeeded(context, output,
                              confidence=max(0.3, min(1.0, quality_total / 100.0)),
                              rationale=("vérification PASS" if all_passed
                                         else f"vérification FAIL — {len(suggestions)} corrections suggérées"))

    def _suggestions(self, verification: dict[str, Any]) -> list[str]:
        suggestions: list[str] = []
        for key in ("self", "physical", "local"):
            for issue in verification.get(key, {}).get("issues", []) or []:
                text = str(issue)
                if text and text not in suggestions:
                    suggestions.append(text)
        return suggestions[:30]


def _stringify_issues(issues: Any) -> list[str]:
    if issues is None:
        return []
    if isinstance(issues, (list, tuple)):
        out: list[str] = []
        for issue in issues:
            if isinstance(issue, dict):
                message = (issue.get("message") or issue.get("description")
                           or issue.get("type") or json_dumps(issue))
                out.append(str(message))
            else:
                out.append(str(issue))
        return out
    return [str(issues)]


def json_dumps(value: Any) -> str:
    import json

    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


def _summary(report: Any) -> dict[str, Any]:
    if isinstance(report, dict):
        return {k: v for k, v in report.items() if k not in ("issues", "violations")}
    out: dict[str, Any] = {}
    for field in ("drc", "erc", "dfm", "passed", "confidence", "score"):
        value = get_field(report, field, default=None)
        if value is not None:
            out[field] = _jsonable(value)
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
