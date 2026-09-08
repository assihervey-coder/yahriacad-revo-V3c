"""Registre des agents — instancie les 10 agents spécialisés V3."""
from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.code_generator_agent import CodeGeneratorAgent
from orchestrator.agent_pipeline.corrector_agent import CorrectorAgent
from orchestrator.agent_pipeline.manufacturing_agent import ManufacturingAgent
from orchestrator.agent_pipeline.placement_agent import PlacementAgent
from orchestrator.agent_pipeline.planner_agent import PlannerAgent
from orchestrator.agent_pipeline.researcher_agent import ResearcherAgent
from orchestrator.agent_pipeline.routing_agent import RoutingAgent
from orchestrator.agent_pipeline.selector_agent import SelectorAgent
from orchestrator.agent_pipeline.simulation_agent import SimulationAgent
from orchestrator.agent_pipeline.validator_agent import ValidatorAgent
from shared.contracts import AgentRole

_AGENT_CLASSES = {
    AgentRole.PLANNER: PlannerAgent,
    AgentRole.RESEARCHER: ResearcherAgent,
    AgentRole.SELECTOR: SelectorAgent,
    AgentRole.CODE_GENERATOR: CodeGeneratorAgent,
    AgentRole.PLACEMENT: PlacementAgent,
    AgentRole.ROUTING: RoutingAgent,
    AgentRole.SIMULATION: SimulationAgent,
    AgentRole.VALIDATOR: ValidatorAgent,
    AgentRole.CORRECTOR: CorrectorAgent,
    AgentRole.MANUFACTURING: ManufacturingAgent,
}


def build_agents(orchestrator: Any = None,
                 versioning: Any = None) -> Dict[AgentRole, BaseAgent]:
    """Instancie les 10 agents (l'orchestrator LLM est optionnel — repli local).

    `versioning` est accepté pour compatibilité d'API : le DesignVersioning
    opérationnel circule par le contexte d'exécution (context["versioning"]).
    """
    agents: Dict[AgentRole, BaseAgent] = {}
    for role, agent_cls in _AGENT_CLASSES.items():
        try:
            agents[role] = agent_cls(orchestrator=orchestrator)
        except TypeError:
            agents[role] = agent_cls()
    return agents


__all__ = ["build_agents", "_AGENT_CLASSES"]
