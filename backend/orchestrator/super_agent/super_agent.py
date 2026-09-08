"""SuperAgent — cerveau décisionnel de haut niveau de la plateforme.

À chaque cycle il décide de la prochaine action :
  delegate | verify | optimize | escalate | export | done

Deux modes :
  - LLM      : si un LLMOrchestrator est fourni, il est prompté (JSON strict),
  - déterministe : machine à états par phase via DecisionPolicy (repli sûr).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from orchestrator.common import get_field
from orchestrator.super_agent.decision_policy.policy import DecisionPolicy
from orchestrator.super_agent.planning.planner import Planner
from shared.contracts import (
    AgentRole,
    ArbitrationPolicy,
    Delegation,
    SuperAgentDecision,
)
from shared.utilities import get_logger, new_id

log = get_logger("super_agent")

VALID_ACTIONS = {"delegate", "verify", "optimize", "escalate", "export", "done"}

# phase → (action, rôle délégué)
PHASE_ACTION: Dict[str, tuple] = {
    "parse": ("delegate", AgentRole.PLANNER),
    "select": ("delegate", AgentRole.SELECTOR),
    "place": ("delegate", AgentRole.PLACEMENT),
    "route": ("delegate", AgentRole.ROUTING),
    "verify": ("verify", None),
    "simulate": ("delegate", AgentRole.SIMULATION),
    "optimize": ("optimize", None),
    "export": ("export", None),
    "done": ("done", None),
}

_SYSTEM_PROMPT = (
    "Tu es le Super Agent d'une plateforme EDA AI-native (PCB_AI_DESIGNER_V3). "
    "À chaque cycle tu choisis la prochaine action parmi: delegate, verify, optimize, "
    "escalate, export, done. Tu réponds STRICTEMENT en JSON: "
    '{"next_action": "...", "rationale": "...", "confidence": 0.0-1.0, '
    '"delegations": [{"role": "planner|researcher|selector|code_generator|placement|'
    'routing|simulation|validator|corrector|manufacturing", "objective": "..."}], '
    '"arbitration": "consensus_confidence|physical_wins|human_first|last_valid_revision"}. '
    "Règles: le cerveau physique (simulateurs, vérifications) a toujours raison; "
    "escalade humaine si les retries sont épuisés ou si la confiance < 0.4."
)


class SuperAgent:
    """Décide du prochain mouvement de l'orchestration globale."""

    def __init__(self, orchestrator: Any = None,
                 policy: Optional[DecisionPolicy] = None,
                 planner: Optional[Planner] = None) -> None:
        self.llm = orchestrator
        self.policy = policy or DecisionPolicy()
        self.planner = planner or Planner()
        self._cycles = 0
        self.log = get_logger("super_agent")

    # ------------------------------------------------------------ décision
    def decide(self, context: Dict[str, Any]) -> SuperAgentDecision:
        """Choisit next_action selon le contexte {phase, design_stats, smm_export,
        verification, conflicts, retries_left, confidence...}."""
        self._cycles += 1
        cycle_id = new_id("cycle")

        phase = str(context.get("phase") or (context.get("signals") or {}).get("phase") or "parse")
        signals = self._signals(context, phase)
        conflicts = context.get("conflicts") or []
        arbitration = self._arbitration_for(conflicts)

        decision = self._llm_decide(cycle_id, context, signals, arbitration)
        if decision is None:
            decision = self._policy_decide(cycle_id, context, signals, conflicts, arbitration)

        decision.metadata.update({
            "cycle": self._cycles,
            "phase": phase,
            "source": decision.metadata.get("source", "policy"),
            "conflicts": len(conflicts),
        })
        self.log.info("cycle %s — phase=%s → %s (%s)",
                      cycle_id, phase, decision.next_action, decision.rationale[:80])
        return decision

    # ------------------------------------------------------------- mode LLM
    def _llm_decide(self, cycle_id: str, context: Dict[str, Any],
                    signals: Dict[str, Any],
                    arbitration: ArbitrationPolicy) -> Optional[SuperAgentDecision]:
        if self.llm is None:
            return None
        user_prompt = json.dumps({
            "phase": signals.get("phase"),
            "design_stats": context.get("design_stats") or {},
            "verification": _truncate(context.get("verification"), 1200),
            "conflicts": context.get("conflicts") or [],
            "signals": {k: v for k, v in signals.items() if k != "phase"},
            "smm_export": str(context.get("smm_export") or "")[:1200],
        }, default=str, ensure_ascii=False)
        try:
            response = self.llm.chat([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
        except Exception as exc:
            self.log.debug("LLM indisponible — fallback déterministe: %s", exc)
            return None
        content = str(get_field(response, "content", default="") or "")
        data = _parse_json(content)
        if not data:
            return None
        next_action = str(data.get("next_action", "")).lower().strip()
        if next_action not in VALID_ACTIONS:
            return None
        delegations: List[Delegation] = []
        for raw in (data.get("delegations") or [])[:6]:
            try:
                role = AgentRole(str(raw.get("role", "")).lower())
            except ValueError:
                continue
            delegations.append(Delegation(
                delegation_id=new_id("del"),
                role=role,
                objective=str(raw.get("objective") or f"exécution {role.value}"),
                context={"source": "super_agent.llm", **(context.get("delegation_context") or {})},
            ))
        try:
            policy_value = ArbitrationPolicy(str(data.get("arbitration", "")).lower())
            chosen_arbitration = policy_value if data.get("arbitration") else arbitration
        except ValueError:
            chosen_arbitration = arbitration
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        return SuperAgentDecision(
            cycle_id=cycle_id,
            next_action=next_action,
            delegations=delegations,
            rationale=str(data.get("rationale") or "décision LLM"),
            global_confidence=confidence,
            arbitration=chosen_arbitration,
            metadata={"source": "llm"},
        )

    # --------------------------------------------------- mode déterministe
    def _policy_decide(self, cycle_id: str, context: Dict[str, Any],
                       signals: Dict[str, Any], conflicts: List[Dict[str, Any]],
                       arbitration: ArbitrationPolicy) -> SuperAgentDecision:
        phase = str(signals.get("phase") or "parse")

        # 1) Conflits → arbitrage explicite
        if conflicts and arbitration == ArbitrationPolicy.HUMAN_FIRST:
            return SuperAgentDecision(
                cycle_id=cycle_id, next_action="escalate",
                rationale=f"{len(conflicts)} conflit(s) non résolus — escalade humaine (HUMAN_FIRST)",
                global_confidence=float(signals.get("confidence", 0.5)),
                arbitration=arbitration,
                metadata={"source": "policy", "conflicts": conflicts[:3]},
            )
        if conflicts:
            return SuperAgentDecision(
                cycle_id=cycle_id, next_action="delegate",
                delegations=[Delegation(
                    delegation_id=new_id("del"),
                    role=AgentRole.CORRECTOR,
                    objective=f"Appliquer l'arbitrage {arbitration.value} sur {len(conflicts)} conflit(s)",
                    context={"conflicts": conflicts, "arbitration": arbitration.value},
                    on_fail="escalate",
                )],
                rationale=f"conflits détectés — arbitrage {arbitration.value}",
                global_confidence=float(signals.get("confidence", 0.6)),
                arbitration=arbitration,
                metadata={"source": "policy"},
            )

        # 2) Escalade prioritaire (retries épuisés / confiance basse)
        if self.policy.should_escalate(signals):
            return SuperAgentDecision(
                cycle_id=cycle_id, next_action="escalate",
                rationale=("retries épuisés après échec de vérification"
                           if not signals.get("verification_passed", True)
                           else f"confiance globale {signals.get('confidence', 0):.2f} < 0.4"),
                global_confidence=float(signals.get("confidence", 0.0)),
                arbitration=arbitration,
                metadata={"source": "policy"},
            )

        # 3) Machine à états — si la phase courante n'a pas encore produit son
        #    output (phase_done=False), on exécute d'abord SON action.
        phase_done = bool(signals.get("phase_done", True))
        if not phase_done:
            next_phase = phase
        else:
            next_phase = self.policy.next_phase(phase, signals)
        if next_phase == "escalate":
            return SuperAgentDecision(
                cycle_id=cycle_id, next_action="escalate",
                rationale=f"politique: rollback impossible depuis {phase}",
                global_confidence=float(signals.get("confidence", 0.4)),
                arbitration=arbitration, metadata={"source": "policy"},
            )
        action, role = PHASE_ACTION.get(next_phase, ("delegate", AgentRole.PLANNER))
        delegations: List[Delegation] = []
        rationale = ""
        if action == "delegate" and role is not None:
            delegations = self.planner.build_plan(context.get("intents"))
            delegations = [d for d in delegations if d.role == role] or [
                Delegation(delegation_id=new_id("del"), role=role,
                           objective=f"exécuter la phase {next_phase}",
                           context={"phase": next_phase})]
            rationale = f"phase {phase} → délégation {role.value}"
        elif action == "verify":
            rationale = f"phase {phase} → vérification complète (self + physique)"
        elif action == "optimize":
            delegations = [Delegation(
                delegation_id=new_id("del"), role=AgentRole.CORRECTOR,
                objective="Optimiser le design (objectif équilibré)",
                context={"action": "optimize", "objective": "balanced"})]
            rationale = "vérification passée → optimisation de la qualité"
        elif action == "export":
            delegations = [Delegation(
                delegation_id=new_id("del"), role=AgentRole.MANUFACTURING,
                objective="Exporter le paquet de fabrication",
                context={"action": "export_design", "fmt": "gerber"})]
            rationale = "design validé → export"
        else:
            rationale = f"phase {phase} → {next_phase}"

        return SuperAgentDecision(
            cycle_id=cycle_id,
            next_action=action,
            delegations=delegations,
            rationale=rationale,
            global_confidence=float(signals.get("confidence", 0.7)),
            arbitration=arbitration,
            metadata={"source": "policy", "next_phase": next_phase},
        )

    # ------------------------------------------------------------ internals
    def _signals(self, context: Dict[str, Any], phase: str) -> Dict[str, Any]:
        signals = dict(context.get("signals") or {})
        verification = context.get("verification") or signals.get("verification") or {}
        passed = bool(get_field(verification, "passed", "ok", default=True)) if verification else True
        signals.setdefault("phase", phase)
        signals.setdefault("verification_passed", passed)
        signals.setdefault("retries_left", int(context.get("retries_left", 0) or 0))
        try:
            confidence = float(context.get("confidence",
                                           signals.get("confidence", 0.7)))
        except (TypeError, ValueError):
            confidence = 0.7
        signals.setdefault("confidence", confidence)
        if signals.get("quality") is None and isinstance(verification, dict):
            quality = (verification.get("quality") or {}).get("total")
            if quality is not None:
                signals["quality"] = quality
        return signals

    def _arbitration_for(self, conflicts: List[Dict[str, Any]]) -> ArbitrationPolicy:
        """Choisit la politique d'arbitrage adaptée aux conflits observés."""
        if not conflicts:
            return ArbitrationPolicy.CONSENSUS_CONFIDENCE
        for conflict in conflicts:
            text = str(conflict.get("subject") or "").lower()
            candidates = conflict.get("candidates") or conflict.get("parties") or []
            physical_involved = any(
                str((c.get("agent") if isinstance(c, dict) else c) or "").lower()
                in {"validator", "simulation", "manufacturing"}
                for c in candidates
            ) or "thermique" in text or "si " in text or "si_" in text
            if physical_involved:
                return ArbitrationPolicy.PHYSICAL_WINS
        return ArbitrationPolicy.CONSENSUS_CONFIDENCE


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrait le premier objet JSON d'une réponse LLM (tolère les fences)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value[:limit]
    return value
