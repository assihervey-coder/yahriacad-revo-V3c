"""Tool-use — spécification, registre et boucle d'exécution des outils."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from shared.utilities import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator

log = get_logger("ai_engine.llm.tool_use")


@dataclass
class ToolSpec:
    """Spécification d'un outil appelable par le LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]          # JSON-schema du payload
    handler: Callable[..., Any]         # fn(**arguments) -> Any

    def openapi(self) -> Dict[str, Any]:
        """Représentation type OpenAI function-calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolLoopResult:
    """Résultat d'une boucle tool-use complète."""

    final_content: str
    tool_calls_made: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 0


class ToolRegistry:
    """Registre des outils exposés au LLM."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Enregistre (ou remplace) un outil."""
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def openapi_schema(self) -> List[Dict[str, Any]]:
        """Schéma complet prêt pour l'API tools."""
        return [t.openapi() for t in self._tools.values()]

    def describe_for_prompt(self) -> str:
        """Description texte des outils, injectée dans le prompt système."""
        if not self._tools:
            return "Outils disponibles : aucun."
        lines = ["Outils disponibles :"]
        for t in self._tools.values():
            params = json.dumps(t.parameters, ensure_ascii=False)
            lines.append(f'- {t.name}: {t.description} | paramètres: {params}')
        lines.append(
            'Pour appeler un outil, réponds UNIQUEMENT avec un JSON '
            '{"tool": "<nom>", "arguments": {...}}.'
        )
        return "\n".join(lines)

    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Exécute un outil par nom, avec erreurs encapsulées."""
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"outil inconnu: {name}")
        return spec.handler(**arguments)


def parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse {"tool": name, "arguments": {...}} dans une réponse LLM (tolérant)."""
    txt = text.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt)
    try:
        data = json.loads(txt)
    except (json.JSONDecodeError, ValueError):
        m = re.search(r'\{[^{}]*"tool"[^{}]*\}', txt, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict) and "tool" in data:
        return {"tool": str(data["tool"]),
                "arguments": data.get("arguments") or {}}
    return None


def run_tool_loop(
    orchestrator: LLMOrchestrator,
    registry: ToolRegistry,
    user_msg: str,
    max_iters: int = 4,
    system_prompt: str | None = None,
) -> ToolLoopResult:
    """Boucle tool-use : LLM → tool_calls JSON → exécution → réinjection.

    Le résultat d'outil est réinjecté avec le marqueur TOOL_RESULT[...] ;
    la boucle s'arrête dès que le LLM ne propose plus d'appel d'outil.
    """
    sys_prompt = system_prompt or (
        "Tu es un agent expert conception PCB. Tu peux utiliser des outils."
    )
    full_system = sys_prompt + "\n" + registry.describe_for_prompt()

    transcript: List[Dict[str, str]] = [{"role": "user", "content": user_msg}]
    calls_made: List[Dict[str, Any]] = []

    for it in range(1, max_iters + 1):
        raw = orchestrator.chat(
            [{"role": "system", "content": full_system}, *transcript],
        ).content

        call = parse_tool_call(raw)
        if call is None:
            return ToolLoopResult(final_content=raw,
                                  tool_calls_made=calls_made, iterations=it)

        tool_name, arguments = call["tool"], call["arguments"]
        calls_made.append(call)
        try:
            output = registry.execute(tool_name, arguments)
            rendered = json.dumps(output, ensure_ascii=False, default=str)[:4000]
        except Exception as exc:  # l'outil ne doit jamais casser la boucle
            log.warning("tool %s a échoué: %s", tool_name, exc)
            rendered = f"ERREUR outil {tool_name}: {exc}"

        transcript.append({"role": "assistant", "content": raw})
        transcript.append({
            "role": "user",
            "content": f"TOOL_RESULT[{tool_name}] {rendered}\n"
                       "Synthétise maintenant la réponse finale pour l'utilisateur.",
        })

    return ToolLoopResult(
        final_content="Limite d'itérations tool-use atteinte.",
        tool_calls_made=calls_made,
        iterations=max_iters,
    )
