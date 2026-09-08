"""Pipelines prédéfinis — séquences d'étapes (agent + action) exécutées par le moteur.

PIPELINES :
  - "full_design" : parse → select → place → route → simulate → verify →
                    optimize → manufacture → export
  - "reoptimize"  : verify → optimize → verify → export
  - "dfm_only"    : verify → manufacture
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from shared.contracts import AgentRole
from shared.utilities import get_logger

log = get_logger("workflow.pipelines")


@dataclass
class Step:
    """Une étape de pipeline : un agent, une action, une politique de retry."""

    name: str
    agent_role: AgentRole
    action: str
    retry: int = 2
    requires: str = "previous"     # "previous" | "" (pas de prérequis)

    def to_dict(self) -> dict:
        return {"name": self.name, "agent_role": self.agent_role.value,
                "action": self.action, "retry": self.retry, "requires": self.requires}


@dataclass
class Pipeline:
    """Pipeline nommé = liste ordonnée d'étapes."""

    name: str
    steps: List[Step] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "steps": [s.to_dict() for s in self.steps]}


def _s(name: str, role: AgentRole, action: str, retry: int = 1) -> Step:
    return Step(name=name, agent_role=role, action=action, retry=retry)


PIPELINES: Dict[str, Pipeline] = {
    "full_design": Pipeline(
        name="full_design",
        description="Chaîne complète intention → paquet de fabrication",
        steps=[
            _s("parse", AgentRole.PLANNER, "parse_plan", retry=1),
            _s("select", AgentRole.SELECTOR, "select_components", retry=1),
            _s("place", AgentRole.PLACEMENT, "place_all", retry=1),
            _s("route", AgentRole.ROUTING, "route_all", retry=1),
            _s("simulate", AgentRole.SIMULATION, "simulate_all", retry=0),
            _s("verify", AgentRole.VALIDATOR, "verify_all", retry=0),
            _s("optimize", AgentRole.CORRECTOR, "optimize", retry=1),
            _s("manufacture", AgentRole.MANUFACTURING, "analyze_and_package", retry=0),
            _s("export", AgentRole.MANUFACTURING, "export_design", retry=1),
        ],
    ),
    "reoptimize": Pipeline(
        name="reoptimize",
        description="Re-vérification, optimisation, re-vérification et export",
        steps=[
            _s("verify", AgentRole.VALIDATOR, "verify_all", retry=0),
            _s("optimize", AgentRole.CORRECTOR, "optimize", retry=1),
            _s("verify_2", AgentRole.VALIDATOR, "verify_all", retry=0),
            _s("export", AgentRole.MANUFACTURING, "export_design", retry=1),
        ],
    ),
    "dfm_only": Pipeline(
        name="dfm_only",
        description="Vérification + analyse manufacturabilité uniquement",
        steps=[
            _s("verify", AgentRole.VALIDATOR, "verify_all", retry=0),
            _s("manufacture", AgentRole.MANUFACTURING, "analyze_and_package", retry=0),
        ],
    ),
}


def get_pipeline(name: str) -> Pipeline:
    """Retourne le pipeline demandé (ValueError explicite si inconnu)."""
    pipeline = PIPELINES.get(name)
    if pipeline is None:
        raise ValueError(f"pipeline inconnu: '{name}' — disponibles: {sorted(PIPELINES)}")
    return pipeline
