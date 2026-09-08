"""Orchestrateur V3 — autonomie du système.

Sous-packages :
  - workflow_engine : pipelines, files de tâches, jobs, moteur d'exécution, runner
  - super_agent     : décision de haut niveau (LLM + machine à états), planning,
                      délégation, arbitrage, politique de décision
  - agent_pipeline  : les 10 agents spécialisés + registre
  - state_manager   : état projets / designs / agents, checkpoints, rollback
"""
from orchestrator.super_agent import SuperAgent
from orchestrator.workflow_engine.engine import WorkflowEngine
from orchestrator.agent_pipeline import BaseAgent, build_agents

__all__ = ["SuperAgent", "WorkflowEngine", "BaseAgent", "build_agents"]
