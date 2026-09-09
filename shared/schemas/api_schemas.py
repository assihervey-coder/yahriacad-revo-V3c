"""Schémas API — requêtes/réponses du chat et erreurs normalisées."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatCommandRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Commande en langage naturel")
    project_id: str = ""
    tenant_id: str = "default"
    session_id: str = ""
    attachments: list[str] = Field(default_factory=list)


class ChatCommandResponse(BaseModel):
    accepted: bool = True
    intent: str = ""
    plan_summary: str = ""
    job_id: str = ""
    reply: str = ""
    agent_activity: list[dict[str, Any]] = Field(default_factory=list)


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
