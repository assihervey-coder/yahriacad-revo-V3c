"""Knowledge Graph — composants, règles électriques, compatibilité, usines."""
from __future__ import annotations

from services.ai_engine.knowledge_graph.compatibility import (
    build_compatibility_edges,
    check_compatibility,
)
from services.ai_engine.knowledge_graph.components import build_component_kg
from services.ai_engine.knowledge_graph.electrical_rules import (
    build_electrical_rules_kg,
    iter_rules,
)
from services.ai_engine.knowledge_graph.kg import Edge, KnowledgeGraph, Node
from services.ai_engine.knowledge_graph.manufacturing import build_manufacturing_kg

__all__ = [
    "KnowledgeGraph",
    "Node",
    "Edge",
    "build_component_kg",
    "build_electrical_rules_kg",
    "iter_rules",
    "check_compatibility",
    "build_compatibility_edges",
    "build_manufacturing_kg",
]
