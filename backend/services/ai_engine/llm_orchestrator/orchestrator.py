"""Orchestrateur LLM — boucle de chat, tools, historique ring buffer, tokens."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from shared.utilities import get_logger
from services.ai_engine.llm_orchestrator.provider import (
    LLMProvider,
    MockLLMProvider,
    get_provider,
)
from services.ai_engine.llm_orchestrator.tool_use import ToolRegistry, run_tool_loop

log = get_logger("ai_engine.llm.orchestrator")


def estimate_tokens(text: str) -> int:
    """Estimation de tokens sans tokenizer lourd (~4 chars/token FR/EN)."""
    return max(1, len(text) // 4)


@dataclass
class LLMResponse:
    """Réponse normalisée de l'orchestrateur."""

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = "mock"
    raw: str = ""


class LLMOrchestrator:
    """Façade unique d'accès au LLM pour tous les agents de la plateforme.

    - délègue au provider (mock déterministe par défaut) ;
    - supporte la boucle tool-use (max 4 itérations) via ToolRegistry ;
    - historise chaque appel (ring buffer 200) et compte les tokens estimés.
    """

    MAX_TOOL_ITERS = 4
    HISTORY_SIZE = 200

    def __init__(self, provider: LLMProvider | None = None,
                 default_system: str | None = None) -> None:
        self.provider: LLMProvider = provider or get_provider()
        self.default_system = default_system or (
            "Tu es un expert en conception électronique et PCB. "
            "Réponds en français, de façon précise et actionnable."
        )
        self.history: List[Dict[str, Any]] = []
        self.usage: Dict[str, int] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    # ------------------------------------------------------------------ chat
    def chat(self, messages: Sequence[Dict[str, str]],
             tools: List[Dict[str, Any]] | ToolRegistry | None = None,
             temperature: float = 0.2,
             system: str | None = None) -> LLMResponse:
        """Chat multi-messages ; si `tools`, exécute la boucle tool-use.

        `tools` peut être une ToolRegistry ou une liste de ToolSpec/ dicts.
        """
        system_prompt = system or self._system_from(messages) or self.default_system
        user_prompt = self._render_messages(messages)

        registry = self._as_registry(tools)
        if registry is not None:
            result = run_tool_loop(
                self, registry, user_prompt, max_iters=self.MAX_TOOL_ITERS,
                system_prompt=system_prompt,
            )
            resp = LLMResponse(
                content=result.final_content,
                tool_calls=result.tool_calls_made,
                usage=self._usage(user_prompt + result.final_content),
                model=self.provider.model_name,
            )
            self._record(system_prompt, user_prompt, resp)
            return resp

        raw = self.provider.complete(system_prompt, user_prompt, temperature)
        resp = LLMResponse(
            content=raw,
            tool_calls=self._extract_tool_calls(raw),
            usage=self._usage(user_prompt + raw),
            model=self.provider.model_name,
            raw=raw,
        )
        self._record(system_prompt, user_prompt, resp)
        return resp

    def ask(self, question: str, system: str | None = None,
            temperature: float = 0.2) -> str:
        """Raccourci une-question → texte."""
        return self.chat([{"role": "user", "content": question}],
                         system=system, temperature=temperature).content

    # ------------------------------------------------------------- internals
    def _usage(self, text: str) -> Dict[str, int]:
        n = estimate_tokens(text)
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += n
        self.usage["completion_tokens"] += n
        return {"prompt_tokens": n, "completion_tokens": n, "total_tokens": n}

    def _record(self, system_prompt: str, user_prompt: str, resp: LLMResponse) -> None:
        self.history.append({
            "ts": time.time(),
            "system": system_prompt[:500],
            "user": user_prompt[:2000],
            "reply": resp.content[:2000],
            "model": resp.model,
            "usage": resp.usage,
        })
        if len(self.history) > self.HISTORY_SIZE:
            del self.history[: len(self.history) - self.HISTORY_SIZE]

    @staticmethod
    def _system_from(messages: Sequence[Dict[str, str]]) -> str | None:
        for m in messages:
            if m.get("role") == "system":
                return m.get("content")
        return None

    @staticmethod
    def _render_messages(messages: Sequence[Dict[str, str]]) -> str:
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                continue
            parts.append(f"[{role.upper()}] {m.get('content', '')}")
        return "\n".join(parts) if parts else ""

    @staticmethod
    def _as_registry(tools: Any) -> ToolRegistry | None:
        if tools is None:
            return None
        if isinstance(tools, ToolRegistry):
            return tools
        registry = ToolRegistry()
        for spec in tools:
            registry.register(spec)
        return registry

    @staticmethod
    def _extract_tool_calls(raw: str) -> List[Dict[str, Any]]:
        """Extrait les tool_calls JSON inline du contenu texte."""
        calls: List[Dict[str, Any]] = []
        txt = raw.strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            txt = txt[4:] if txt.lower().startswith("json") else txt
        try:
            data = json.loads(txt)
            if isinstance(data, dict) and "tool" in data:
                calls.append({"tool": data["tool"],
                              "arguments": data.get("arguments", {})})
        except (json.JSONDecodeError, ValueError):
            pass
        return calls


_ORCH: LLMOrchestrator | None = None


def get_llm_orchestrator() -> LLMOrchestrator:
    """Orchestrateur singleton (provider selon env)."""
    global _ORCH
    if _ORCH is None:
        _ORCH = LLMOrchestrator()
    return _ORCH
