"""Schémas des agents — tâches, résultats, messages inter-agents."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ESCALATED = "escalated"   # escalade vers l'humain


class AgentTaskSchema(BaseModel):
    task_id: str
    role: str                      # AgentRole value
    action: str                    # "place_all", "route_net", "verify_drc"...
    payload: dict[str, Any] = Field(default_factory=dict)
    project_id: str = ""
    revision: int = 0
    deadline_ms: int | None = None
    priority: int = 5              # 1 (haute) → 9 (basse)


class AgentResultSchema(BaseModel):
    task_id: str
    role: str
    status: AgentStatus = AgentStatus.PENDING
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0        # 0..1 — écrit aussi dans shared_mental_model
    rationale: str = ""
    revision_created: int | None = None
    rollback_to: int | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # nom → uri
