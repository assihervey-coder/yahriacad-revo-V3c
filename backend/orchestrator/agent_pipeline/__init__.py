"""Pipeline d'agents — base contractuelle, les 10 agents V3 et le registre."""
from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.agent_pipeline.registry import build_agents

__all__ = ["BaseAgent", "build_agents"]
