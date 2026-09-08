"""PlannerAgent — transforme l'intention utilisateur en plan de délégations."""
from __future__ import annotations

from typing import Any, Dict

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import get_field, try_import
from orchestrator.super_agent.planning.planner import Planner
from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema
from shared.schemas.agent_schemas import AgentStatus
from shared.utilities import new_id


class PlannerAgent(BaseAgent):
    """Étape `parse` : IntentParser (si besoin) → Planner → plan de délégations."""

    role = AgentRole.PLANNER
    description = "Transforme l'intention en plan ordonné de délégations par rôle."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.PLANNER, "planner", orchestrator)
        self._planner = Planner()

    def plan(self, objective: str, context: Dict[str, Any]) -> list[str]:
        return ["parser l'intention", "construire le plan", "enregistrer dans le SMM"]

    def supports(self, action: str) -> bool:
        return action in ("parse_plan", "parse", "plan", "delegate", "")

    def execute(self, context: Dict[str, Any]) -> AgentResultSchema:
        message = str(context.get("message") or "")
        intents = context.get("intents")
        parse_meta: Dict[str, Any] = {"source": "context"}

        # 1) IntentGraph — créée par IntentParser si absente
        if intents is None:
            parser_mod = try_import("services.ai_engine", ["IntentParser"])
            parser_cls = parser_mod.get("IntentParser")
            if parser_cls is not None:
                try:
                    try:
                        parser = parser_cls()
                    except TypeError:
                        parser = parser_cls(self.orchestrator)
                    result = parser.parse(message or "conception de carte électronique")
                    intents = parser.to_intent_graph(result)
                    parse_meta = {
                        "source": "intent_parser",
                        "project_type": str(get_field(result, "project_type", default="") or ""),
                        "layers": get_field(result, "layers", default=None),
                        "confidence": float(get_field(result, "confidence", default=0.7) or 0.7),
                        "component_hints": [
                            str(h) for h in (get_field(result, "component_hints", default=[]) or [])
                        ][:20],
                    }
                    context["intents"] = intents
                except Exception as exc:
                    self.log.debug("IntentParser indisponible: %s", exc)
                    parse_meta = {"source": "fallback", "error": str(exc)}
            else:
                parse_meta = {"source": "fallback", "error": "services.ai_engine.IntentParser absent"}
        context["intent_parse"] = {**parse_meta, "message_length": len(message)}

        # 2) Plan de délégations
        try:
            plan = self._planner.build_plan(intents)
        except Exception as exc:
            return self.failed(context, f"planification impossible: {exc}")

        output = {
            "plan": [
                {
                    "delegation_id": d.delegation_id,
                    "role": d.role.value,
                    "objective": d.objective,
                    "acceptance_criteria": d.acceptance_criteria,
                }
                for d in plan
            ],
            "steps": [d.role.value for d in plan],
            "goal_count": len(plan),
            "parse": parse_meta,
        }

        self.record_decision(
            context, "plan",
            f"plan en {len(plan)} délégations: {' -> '.join(output['steps'])}",
            confidence=0.8,
        )
        self.emit("intent.parsed", {"steps": output["steps"], **parse_meta}, context)
        return self.succeeded(
            context, output,
            confidence=float(parse_meta.get("confidence", 0.75) or 0.75),
            rationale=f"plan: {' -> '.join(output['steps'])}",
        )
