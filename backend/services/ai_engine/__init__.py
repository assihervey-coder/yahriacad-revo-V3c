"""AI Engine — le cerveau de PCB_AI_DESIGNER_V3.

Sous-modules :
- llm_orchestrator        : cerveau symbolique (LLM, tools, prompts, intentions)
- rag_engine              : récupération de connaissance (TF-IDF maison + LLM)
- knowledge_graph         : graphe de connaissance composants/règles/usines
- rl_agent                : cerveau décisionnel (policy/value/world model REINFORCE)
- self_verifier           : auto-vérification + confiance + rollback
- autonomous_optimizer    : optimisation autonome (proposers, keeper, évol./bayésien)
- training                : génération d'épisodes + pipeline REINFORCE + checkpoints
"""
from __future__ import annotations

__version__ = "3.0.0"

# Réexports de haut niveau (imports paresseux pour rester léger et robuste
# quand design_core n'est pas encore disponible).
__all__ = [
    "LLMOrchestrator",
    "IntentParser",
    "RAGEngine",
    "KnowledgeGraph",
    "RLAgent",
    "SelfVerifier",
    "RollbackManager",
    "AutonomousOptimizer",
    "get_llm_orchestrator",
    "get_intent_parser",
    "get_rag_engine",
]


def __getattr__(name: str):  # PEP 562 — réexport paresseux
    if name == "LLMOrchestrator":
        from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator

        return LLMOrchestrator
    if name == "IntentParser":
        from services.ai_engine.llm_orchestrator.intent_parser import IntentParser

        return IntentParser
    if name == "RAGEngine":
        from services.ai_engine.rag_engine.rag_engine import RAGEngine

        return RAGEngine
    if name == "KnowledgeGraph":
        from services.ai_engine.knowledge_graph.kg import KnowledgeGraph

        return KnowledgeGraph
    if name == "RLAgent":
        from services.ai_engine.rl_agent.rl_agent import RLAgent

        return RLAgent
    if name == "SelfVerifier":
        from services.ai_engine.self_verifier.verifier import SelfVerifier

        return SelfVerifier
    if name == "RollbackManager":
        from services.ai_engine.self_verifier.rollback_manager import RollbackManager

        return RollbackManager
    if name == "AutonomousOptimizer":
        from services.ai_engine.autonomous_optimizer.optimizer import AutonomousOptimizer

        return AutonomousOptimizer
    if name == "get_llm_orchestrator":
        from services.ai_engine.llm_orchestrator.orchestrator import get_llm_orchestrator

        return get_llm_orchestrator
    if name == "get_intent_parser":
        from services.ai_engine.llm_orchestrator.intent_parser import get_intent_parser

        return get_intent_parser
    if name == "get_rag_engine":
        from services.ai_engine.rag_engine.rag_engine import get_rag_engine

        return get_rag_engine
    raise AttributeError(f"module 'services.ai_engine' has no attribute {name!r}")
