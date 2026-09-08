"""Planner — transforme les intentions en délégations ordonnées par rôle."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.common import get_field
from shared.contracts import AgentRole, Delegation
from shared.utilities import get_logger, new_id

log = get_logger("super_agent.planner")

# Séquence canonique quand aucun indice thématique n'est détecté
DEFAULT_SEQUENCE: List[AgentRole] = [
    AgentRole.SELECTOR,
    AgentRole.PLACEMENT,
    AgentRole.ROUTING,
    AgentRole.VALIDATOR,
    AgentRole.SIMULATION,
    AgentRole.CORRECTOR,
    AgentRole.MANUFACTURING,
]

# Heuristique LLM-less : mots-clés d'intention → rôle
KEYWORD_ROLES: List[Tuple[Tuple[str, ...], AgentRole]] = [
    (("composant", "component", "sélection", "select", "bom", "référence"), AgentRole.SELECTOR),
    (("place", "position", "implantation"), AgentRole.PLACEMENT),
    (("route", "routage", "piste", "net "), AgentRole.ROUTING),
    (("simul", "thermique", "integrité", "intégrité", "cem", "emi", "si ", "pi "), AgentRole.SIMULATION),
    (("verif", "vérif", "drc", "erc", "dfm", "contrôle"), AgentRole.VALIDATOR),
    (("corrige", "corrigé", "fix", "optimi"), AgentRole.CORRECTOR),
    (("manufact", "fabriqu", "devis", "quote", "jlcpcb", "pcbway"), AgentRole.MANUFACTURING),
    (("code", "skidl", "script", "netlist"), AgentRole.CODE_GENERATOR),
    (("recherche", "research", "datasheet", "doc"), AgentRole.RESEARCHER),
]

# Ordre canonique de dépendances (plus petit = plus tôt)
CANONICAL_ORDER: Dict[AgentRole, int] = {
    AgentRole.PLANNER: 0,
    AgentRole.RESEARCHER: 1,
    AgentRole.CODE_GENERATOR: 2,
    AgentRole.SELECTOR: 3,
    AgentRole.PLACEMENT: 4,
    AgentRole.ROUTING: 5,
    AgentRole.VALIDATOR: 6,
    AgentRole.SIMULATION: 7,
    AgentRole.CORRECTOR: 8,
    AgentRole.MANUFACTURING: 9,
}

OBJECTIVES: Dict[AgentRole, str] = {
    AgentRole.PLANNER: "Parser l'intention et produire le plan d'exécution",
    AgentRole.RESEARCHER: "Rechercher les contraintes techniques des composants",
    AgentRole.SELECTOR: "Sélectionner les composants et construire le DesignGraph",
    AgentRole.CODE_GENERATOR: "Générer le script SKIDL du design",
    AgentRole.PLACEMENT: "Placer les composants (HPWL minimal)",
    AgentRole.ROUTING: "Router les nets (100% de routage visé)",
    AgentRole.SIMULATION: "Simuler thermique / SI / PI / CEM",
    AgentRole.VALIDATOR: "Vérifier DRC/ERC/DFM et scorer la qualité",
    AgentRole.CORRECTOR: "Corriger les violations et optimiser",
    AgentRole.MANUFACTURING: "Analyser la manufacturabilité et préparer le package",
}


class Planner:
    """Planification heuristique (enrichissable par LLM) des délégations."""

    def build_plan(self, intents: Any) -> List[Delegation]:
        """Intentions prioritaires → délégations ordonnées par rôle."""
        goals = self._goals(intents)
        text = " ".join(goals).lower()
        roles: List[AgentRole] = []
        for keywords, role in KEYWORD_ROLES:
            for keyword in keywords:
                if keyword in text and role not in roles:
                    roles.append(role)
                    break
        if not roles:
            roles = list(DEFAULT_SEQUENCE)
        roles = self._canonical_order(roles)
        return [
            Delegation(
                delegation_id=new_id("del"),
                role=role,
                objective=OBJECTIVES[role],
                acceptance_criteria=self._criteria(role),
                context={"goals": goals[:6], "source": "planner"},
                max_iterations=3,
                requires_verification=role not in (AgentRole.PLANNER, AgentRole.RESEARCHER),
                on_fail="rollback",
            )
            for role in roles
        ]

    def replan(self, plan: List[Delegation], feedback: Dict[str, Any]) -> List[Delegation]:
        """Re-planifie : retire les rôles en échec, injecte une correction."""
        failed_roles = set()
        for role in (feedback.get("failed_roles") or []):
            try:
                failed_roles.add(AgentRole(str(role)))
            except ValueError:
                continue
        if feedback.get("verification_failed"):
            failed_roles.add(AgentRole.CORRECTOR)
        replanned: List[Delegation] = []
        for delegation in plan:
            if delegation.role in failed_roles and delegation.role != AgentRole.CORRECTOR:
                continue
            replanned.append(delegation)
        if failed_roles and AgentRole.CORRECTOR not in {d.role for d in replanned}:
            insert_at = len(replanned)
            for index, delegation in enumerate(replanned):
                if delegation.role == AgentRole.MANUFACTURING:
                    insert_at = index
                    break
            reason = str(feedback.get("reason") or "échec détecté")
            replanned.insert(insert_at, Delegation(
                delegation_id=new_id("del"),
                role=AgentRole.CORRECTOR,
                objective=f"Corriger les issues détectées ({reason[:80]})",
                acceptance_criteria=["aucune violation bloquante restante"],
                context={"feedback": feedback, "source": "replan"},
                on_fail="escalate",
            ))
        return self._canonical_order(replanned)

    # ------------------------------------------------------------ internals
    def _goals(self, intents: Any) -> List[str]:
        if intents is None:
            return []
        if isinstance(intents, str):
            return [intents]
        for attr in ("priority_goals", "goals", "priorities", "objectives"):
            value = get_field(intents, attr, default=None)
            if isinstance(value, list) and value:
                return [str(goal) for goal in value]
        goals: List[str] = []
        hints = get_field(intents, "component_hints", "components", default=None)
        if isinstance(hints, list) and hints:
            goals.append("composants: " + ", ".join(str(h) for h in hints[:10]))
        for attr in ("raw", "raw_text", "description", "message"):
            text = get_field(intents, attr, default=None)
            if isinstance(text, str) and text.strip():
                goals.append(text.strip())
                break
        return goals

    def _canonical_order(self, roles: List[AgentRole]) -> List[AgentRole]:
        seen: List[AgentRole] = []
        for role in sorted(set(roles), key=lambda r: CANONICAL_ORDER.get(r, 99)):
            seen.append(role)
        return seen

    def _criteria(self, role: AgentRole) -> List[str]:
        criteria: Dict[AgentRole, List[str]] = {
            AgentRole.SELECTOR: ["tous les component hints matchés", "graph avec ≥1 composant"],
            AgentRole.PLACEMENT: ["aucun recouvrement", "longueur de fil réduite"],
            AgentRole.ROUTING: ["100% des nets routés ou échecs justifiés"],
            AgentRole.SIMULATION: ["simulations exécutées", "verdicts disponibles"],
            AgentRole.VALIDATOR: ["rapport self + physique produits"],
            AgentRole.CORRECTOR: ["issues corrigées ou escalade justifiée"],
            AgentRole.MANUFACTURING: ["analyse DFM + package prêts"],
            AgentRole.PLANNER: ["plan en ≥3 délégations"],
            AgentRole.RESEARCHER: ["réponse documentaire enregistrée"],
            AgentRole.CODE_GENERATOR: ["script SKIDL non vide"],
        }
        return criteria.get(role, ["objectif atteint"])
