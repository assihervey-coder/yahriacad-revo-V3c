"""Contrats d'agents — rôles, messages, décisions du Super Agent.

Ces contrats sont la référence unique pour orchestrator/, ai_engine/ et l'API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(str, Enum):
    """Les 10 agents spécialisés de la plateforme."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    SELECTOR = "selector"
    CODE_GENERATOR = "code_generator"
    PLACEMENT = "placement"
    ROUTING = "routing"
    SIMULATION = "simulation"
    VALIDATOR = "validator"
    CORRECTOR = "corrector"
    MANUFACTURING = "manufacturing"


class BrainType(str, Enum):
    """Les trois cerveaux V3 — chaque agent appartient à un cerveau dominant."""

    SYMBOLIC = "symbolic"      # 🧠 LLM/RAG/KG — quoi construire
    DECISION = "decision"      # 🤖 RL — comment agir géométriquement
    PHYSICAL = "physical"      # 🔬 simulateurs — est-ce vrai


ROLE_BRAIN: Dict[AgentRole, BrainType] = {
    AgentRole.PLANNER: BrainType.SYMBOLIC,
    AgentRole.RESEARCHER: BrainType.SYMBOLIC,
    AgentRole.SELECTOR: BrainType.SYMBOLIC,
    AgentRole.CODE_GENERATOR: BrainType.SYMBOLIC,
    AgentRole.PLACEMENT: BrainType.DECISION,
    AgentRole.ROUTING: BrainType.DECISION,
    AgentRole.SIMULATION: BrainType.PHYSICAL,
    AgentRole.VALIDATOR: BrainType.PHYSICAL,
    AgentRole.CORRECTOR: BrainType.DECISION,   # mixte LLM+RL à l'usage
    AgentRole.MANUFACTURING: BrainType.PHYSICAL,
}


class ArbitrationPolicy(str, Enum):
    """Résolution de conflits entre agents (super_agent/arbitration)."""

    CONSENSUS_CONFIDENCE = "consensus_confidence"   # vote pondéré par confiance
    PHYSICAL_WINS = "physical_wins"                 # le cerveau physique a toujours raison
    HUMAN_FIRST = "human_first"                     # escalade humaine
    LAST_VALID_REVISION = "last_valid_revision"     # rollback design_versioning


@dataclass
class AgentMessage:
    """Message inter-agents (pipeline)."""

    sender: AgentRole
    recipient: AgentRole | str      # rôle ou "super_agent" / "broadcast"
    subject: str                    # ex "placement_done", "drc_violations"
    body: Dict[str, Any] = field(default_factory=dict)
    requires_reply: bool = False


@dataclass
class Delegation:
    """Délégation décidée par le super_agent (planning → exécution)."""

    delegation_id: str
    role: AgentRole
    objective: str
    context: Dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: List[str] = field(default_factory=list)
    max_iterations: int = 3
    requires_verification: bool = True
    on_fail: str = "rollback"       # rollback | escalate | retry


@dataclass
class SuperAgentDecision:
    """Sortie du super_agent à chaque cycle de décision."""

    cycle_id: str
    next_action: str                # delegate | verify | optimize | escalate | export | done
    delegations: List[Delegation] = field(default_factory=list)
    rationale: str = ""
    global_confidence: float = 0.0
    arbitration: ArbitrationPolicy = ArbitrationPolicy.CONSENSUS_CONFIDENCE
    metadata: Dict[str, Any] = field(default_factory=dict)
