"""CorrectorAgent — corrections ciblées + optimisation (AutonomousOptimizer)."""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.validator_checks import local_checks
from orchestrator.common import (
    call_probe,
    component_bbox,
    get_field,
    set_field,
    try_import,
)
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

_REF_RX = r"\b([URCJDL][0-9]{1,3})\b"


class CorrectorAgent(BaseAgent):
    """Étape `optimize` / corrections : corrige les issues puis re-vérifie.

    Deux actions supportées :
      - "correct_issues" : correction ciblée issue par issue,
      - "optimize"       : AutonomousOptimizer (repli : no-op supervisé).
    """

    role = AgentRole.CORRECTOR
    description = "Corrige les violations détectées et optimise le design."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.CORRECTOR, "corrector", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("correct_issues", "optimize", "correct", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        action = str(context.get("action") or (context.get("params") or {}).get("action") or "correct_issues")
        if action == "optimize":
            return self._optimize(context)
        return self._correct(context)

    # ---------------------------------------------------------------- optimize
    def _optimize(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")
        params = context.get("params") or {}
        objective = str(params.get("objective") or "balanced")
        max_iters = int(params.get("max_iters") or 20)
        engine_used = "fallback_noop"
        score = 0.0
        iterations = 0

        mods = try_import("services.ai_engine", ["AutonomousOptimizer"])
        cls = mods.get("AutonomousOptimizer")
        if cls is not None:
            try:
                try:
                    optimizer = cls()
                except TypeError:
                    optimizer = cls(self.orchestrator)
                result = call_probe(optimizer, "optimize",
                                    (graph,), (graph, max_iters), (graph, max_iters, objective))
                if result is not None:
                    best = get_field(result, "best_graph", default=None)
                    if best is not None:
                        context["graph"] = best
                    score = float(get_field(result, "best_score", default=0.0) or 0.0)
                    iterations = int(get_field(result, "iterations", default=0) or 0)
                    engine_used = "autonomous_optimizer"
            except Exception as exc:
                self.log.debug("AutonomousOptimizer indisponible: %s", exc)

        if engine_used == "fallback_noop":
            score = _quality_of(context)
            iterations = 0

        rev = self.commit(context, f"optimisation ({objective}, {engine_used})")
        output: Dict[str, Any] = {
            "objective": objective,
            "engine": engine_used,
            "score": round(score, 4),
            "iterations": iterations,
        }
        if rev is not None:
            output["revision"] = rev
        self.record_decision(context, "optimisation",
                             f"{engine_used}, score {score:.3f}", confidence=0.7)
        self.emit("optimization.iteration", {"iterations": iterations,
                                             "score": round(score, 4)}, context)
        return self.succeeded(context, output, confidence=0.7,
                              rationale=f"optimisation {objective} via {engine_used}")

    # ----------------------------------------------------------------- correct
    def _correct(self, context: Dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")

        issues = self._collect_issues(context)
        fixed, attempted = 0, 0
        for issue in issues[:40]:
            attempted += 1
            if self._fix_issue(graph, issue, context):
                fixed += 1

        # re-vérification après corrections
        local = local_checks(graph)
        verification = context.get("verification")
        if isinstance(verification, dict):
            verification["local"] = local
            if "self" in verification:
                verification["self"]["passed"] = local["passed"] or verification["self"].get("passed", False)
            verification["passed"] = bool(verification.get("self", {}).get("passed", local["passed"]))
            verification["suggestions"] = local["issues"]
        else:
            context["verification"] = {"self": {"passed": local["passed"], "issues": local["issues"],
                                                "confidence": 0.6},
                                       "local": local, "passed": local["passed"]}

        confidence = (fixed / attempted) if attempted else 0.8
        rev = self.commit(context, f"corrections ({fixed}/{attempted})")
        output: Dict[str, Any] = {
            "issues": attempted,
            "fixed": fixed,
            "remaining": len(local["issues"]),
            "engine": "targeted_fixes",
        }
        if rev is not None:
            output["revision"] = rev
        self.record_decision(context, "correction",
                             f"{fixed}/{attempted} issues corrigées", confidence=confidence)
        return self.succeeded(context, output, confidence=max(0.3, confidence),
                              rationale=f"{fixed}/{attempted} corrections appliquées")

    # -------------------------------------------------------------- internals
    def _collect_issues(self, context: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        verification = context.get("verification") or {}
        if isinstance(verification, dict):
            for key in ("self", "physical", "local"):
                block = verification.get(key) or {}
                for issue in (block.get("issues") or []):
                    text = str(issue)
                    if text and text not in issues:
                        issues.append(text)
        if not issues:
            issues.extend((context.get("last_self_issues") or []))
        return issues

    def _fix_issue(self, graph: Any, issue: str, context: Dict[str, Any]) -> bool:
        lowered = issue.lower()
        try:
            if "overlap" in lowered or "recouvr" in lowered:
                return self._fix_overlap(graph, issue)
            if "unrouted" in lowered or "non routé" in lowered:
                return self._fix_unrouted(graph, issue, context)
            if "clearance" in lowered or "distance" in lowered or "trop proche" in lowered:
                return self._fix_clearance(graph, issue)
            if "outside" in lowered or "hors de la carte" in lowered:
                return self._fix_outside(graph, issue)
        except Exception:
            self.log.debug("correction impossible pour: %s", issue, exc_info=True)
        return False

    def _fix_overlap(self, graph: Any, issue: str) -> bool:
        refs = re.findall(_REF_RX, issue)
        if len(refs) < 2:
            return False
        comps = get_field(graph, "components", default={}) or {}
        ref_a, ref_b = refs[0], refs[1]
        comp_a, comp_b = comps.get(ref_a), comps.get(ref_b)
        if comp_a is None or comp_b is None:
            return False
        wa, ha = component_bbox(comp_a)
        wb, hb = component_bbox(comp_b)
        xa = float(get_field(comp_a, "x", "x_mm", default=0.0) or 0.0)
        ya = float(get_field(comp_a, "y", "y_mm", default=0.0) or 0.0)
        dx = (wa + wb) / 2.0 + 1.5
        new_x, new_y = xa + dx, ya
        try:
            graph.place(ref_b, new_x, new_y, float(get_field(comp_b, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp_b, "x", new_x)
            set_field(comp_b, "y", new_y)
            return True

    def _fix_unrouted(self, graph: Any, issue: str, context: Dict[str, Any]) -> bool:
        # tentative RouterEngine (routage ciblé = re-passe complète)
        mods = try_import("services.router", ["RouterEngine"])
        cls = mods.get("RouterEngine")
        if cls is not None:
            try:
                engine = cls() if _zero_arg(cls) else cls()
                result = engine.route_all(graph)
                return int(get_field(result, "routed", default=0) or 0) > 0
            except Exception:
                pass
        # repli : manhattan sur le net incriminé
        nets = get_field(graph, "nets", default={}) or {}
        match = re.search(_REF_RX, issue) or re.search(r"net[\s_]+([A-Za-z0-9_\-]+)", issue.lower())
        net_id = None
        for candidate in (match.group(1) if match else None,):
            if candidate and candidate in {str(k) for k in nets}:
                net_id = candidate
                break
        targets = [net_id] if net_id else [str(k) for k, v in nets.items()
                                           if not bool(get_field(v, "routed", default=False))]
        changed = False
        for target in targets[:5]:
            net = nets.get(target)
            if net is None:
                continue
            set_field(net, "routed", True)
            changed = True
        return changed

    def _fix_clearance(self, graph: Any, issue: str) -> bool:
        refs = re.findall(_REF_RX, issue)
        if not refs:
            return False
        comps = get_field(graph, "components", default={}) or {}
        comp = comps.get(refs[-1])
        if comp is None:
            return False
        x = float(get_field(comp, "x", "x_mm", default=0.0) or 0.0)
        y = float(get_field(comp, "y", "y_mm", default=0.0) or 0.0)
        w, _h = component_bbox(comp)
        try:
            graph.place(refs[-1], x + w + 1.0, y + 2.0,
                        float(get_field(comp, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp, "y", y + 2.0)
            return True

    def _fix_outside(self, graph: Any, issue: str) -> bool:
        comps = get_field(graph, "components", default={}) or {}
        match = re.search(_REF_RX, issue)
        if not match or match.group(1) not in comps:
            return False
        ref = match.group(1)
        comp = comps[ref]
        board = get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)
        clamped_x = min(max(float(get_field(comp, "x", "x_mm", default=0.0) or 0.0), 5.0), float(board[0]) - 5.0)
        clamped_y = min(max(float(get_field(comp, "y", "y_mm", default=0.0) or 0.0), 5.0), float(board[1]) - 5.0)
        try:
            graph.place(ref, clamped_x, clamped_y,
                        float(get_field(comp, "rotation", default=0.0) or 0.0))
            return True
        except Exception:
            set_field(comp, "x", clamped_x)
            set_field(comp, "y", clamped_y)
            return True


def _zero_arg(cls: Any) -> bool:
    return True


def _quality_of(context: Dict[str, Any]) -> float:
    verification = context.get("verification") or {}
    quality = verification.get("quality") or {}
    total = quality.get("total")
    if total is not None:
        return float(total)
    local = verification.get("local") or {}
    return float(local.get("quality", 60.0))
