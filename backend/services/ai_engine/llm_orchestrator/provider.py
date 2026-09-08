"""Providers LLM — Protocol + implémentations mock / OpenAI / Z-AI.

Le provider par défaut est DÉTERMINISTE (MockLLMProvider) : la plateforme
fonctionne sans clé API et le comportement est reproductible pour les tests.
Les providers réels (openai, httpx) sont importés en lazy avec fallback.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Protocol, runtime_checkable

from shared.utilities import get_logger

log = get_logger("ai_engine.llm.provider")


@runtime_checkable
class LLMProvider(Protocol):
    """Contrat minimal d'un provider LLM."""

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Génère une complétion pour (system, user)."""
        ...

    @property
    def model_name(self) -> str:
        """Identifiant du modèle (pour usage/télémétrie)."""
        ...


def _extract_question(user: str) -> str:
    """Extrait la question principale (dernière ligne utile, sans tag de rôle)."""
    for line in reversed([ln.strip() for ln in user.splitlines()]):
        if not line or line.startswith(("[", "{", "#", "Résultat", "TOOL_RESULT")):
            continue
        return re.sub(r"^\[(?:USER|ASSISTANT|SYSTEM)\]\s*", "", line, flags=re.IGNORECASE)
    return user.strip()


def _guess_tool_arguments(tool_name: str, user: str) -> Dict[str, Any]:
    """Devine des arguments plausibles pour un outil (mode déterministe)."""
    low = tool_name.lower()
    question = _extract_question(user)
    if any(k in low for k in ("search", "knowledge", "rag", "query", "lookup")):
        return {"query": question, "k": 3}
    if any(k in low for k in ("parse", "intent")):
        return {"text": question}
    if any(k in low for k in ("plan", "decompose")):
        return {"objective": question}
    if any(k in low for k in ("verify", "check")):
        return {}
    if any(k in low for k in ("place", "move")):
        return {"ref": "U1", "dx": 1.0, "dy": 0.0}
    return {}


def _find_tool_name(text: str) -> str | None:
    """Repère un nom d'outil dans le message (registre « Outils disponibles »)."""
    m = re.search(r'"name"\s*:\s*"([a-z_0-9]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|\n)-\s*([a-z_][a-z_0-9]+)\s*[:(]", text)
    if m:
        return m.group(1)
    m = re.search(r"Outils?\s*disponibles?\s*:\s*([a-z_,\s]+)", text, re.IGNORECASE)
    if m:
        parts = [p.strip(" -") for p in m.group(1).split(",") if p.strip(" -")]
        if parts:
            return parts[0]
    return None


class MockLLMProvider:
    """Provider déterministe — réponses structurées utiles basées sur mots-clés.

    Garde un historique des appels (ring buffer) ; aucune dépendance externe.
    """

    def __init__(self, history_size: int = 200) -> None:
        self.model = "mock-deterministic-v3"
        self.history: List[Dict[str, Any]] = []
        self._history_size = history_size
        self.call_count = 0

    @property
    def model_name(self) -> str:
        return self.model

    # ------------------------------------------------------------------ core
    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        self.call_count += 1
        self.history.append({
            "system": system,
            "user": user,
            "temperature": temperature,
        })
        if len(self.history) > self._history_size:
            del self.history[: len(self.history) - self._history_size]

        reply = self._route(system, user)
        self.history[-1]["reply"] = reply
        return reply

    # ------------------------------------------------------------- routage
    def _route(self, system: str, user: str) -> str:
        text = f"{system}\n{user}".lower()

        # 1) Boucle tool-use : le résultat d'outil est réinjecté → synthèse
        if "tool_result" in text or "résultat de l'outil" in text:
            return self._final_answer_after_tool(user)

        # 2) Des outils sont annoncés → émettre un appel d'outil JSON
        if "outil" in text or "tool" in text:
            tool = _find_tool_name(system + "\n" + user)
            if tool:
                args = _guess_tool_arguments(tool, user)
                return json.dumps(
                    {"tool": tool, "arguments": args},
                    ensure_ascii=False,
                    sort_keys=True,
                )

        # 3) Intention → JSON structuré d'intention
        if "intent" in text or "intention" in text:
            return self._intent_json(user)

        # 4) Plan → liste d'étapes
        if "plan" in text or "étapes" in text or "steps" in text:
            return self._plan(user)

        # 5) SKIDL / netlist → JSON composants
        if "skidl" in text or "netlist" in text or "composants" in text:
            return self._skidl(user)

        # 6) Paragraphe générique expert
        return self._generic(user)

    # --------------------------------------------------------- générateurs
    def _intent_json(self, user: str) -> str:
        question = _extract_question(user)
        low = question.lower()
        ptype = "generic"
        if any(k in low for k in ("esp32", "capteur", "sensor", "iot", "ble", "wifi")):
            ptype = "iot_sensor"
        elif any(k in low for k in ("stm32", "mcu", "microcontrôleur", "microcontroller")):
            ptype = "mcu_board"
        elif any(k in low for k in ("alim", "power", "ldo", "buck", "convertisseur")):
            ptype = "power"
        elif any(k in low for k in ("rf", "antenne", "antenna", "lora", "gps")):
            ptype = "rf"
        layers = 2
        m = re.search(r"(\d+)\s*(?:couches?|layers?|layer)", low)
        if m:
            layers = int(m.group(1))
        size = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", low)
        if m:
            size = [float(m.group(1)), float(m.group(2))]
        factory = None
        if "jlcpcb" in low:
            factory = "jlcpcb"
        elif "pcbway" in low:
            factory = "pcbway"
        payload = {
            "project_type": ptype,
            "layers": layers,
            "board_size": size,
            "component_hints": [w for w in ("esp32", "usb-c", "capteur", "stm32") if w in low],
            "constraints_text": [question],
            "target_factory": factory,
            "priority_goals": ["fiabilité", "coût", "manufacturabilité"],
            "confidence": 0.75,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _plan(self, user: str) -> str:
        question = _extract_question(user)
        return (
            "Plan proposé :\n"
            "1. Parser l'intention et identifier le type de carte.\n"
            "2. Sélectionner les composants (MPN, empreintes, disponibilité).\n"
            "3. Générer le schéma netlist puis placer les composants.\n"
            "4. Router les nets critiques d'abord (alimentation, haut débit).\n"
            "5. Simuler (thermique, SI) et vérifier DRC/ERC/DFM.\n"
            "6. Corriger les violations puis exporter le package manufacturing.\n"
            f"Objectif : {question}"
        )

    def _skidl(self, user: str) -> str:
        return json.dumps({
            "components": [
                {"ref": "U1", "mpn": "ESP32-WROOM-32E", "footprint": "ESP32-WROOM-32x"},
                {"ref": "C1", "mpn": "CL21B104KBNNPNC", "footprint": "C_0402_1005Metric"},
            ],
            "nets": [
                {"name": "3V3", "pins": [["U1", "1"], ["C1", "1"]]},
                {"name": "GND", "pins": [["U1", "2"], ["C1", "2"]]},
            ],
        }, ensure_ascii=False)

    def _final_answer_after_tool(self, user: str) -> str:
        m = re.search(r"TOOL_RESULT\[(.*?)\]", user, re.DOTALL)
        fragment = m.group(1).strip()[:400] if m else ""
        return (
            "Voici la synthèse : l'outil a répondu — "
            + (fragment if fragment else "aucun résultat exploitable")
            + ". Je peux préciser si besoin."
        )

    def _generic(self, user: str) -> str:
        question = _extract_question(user)
        return (
            "En tant qu'expert conception PCB : pour « "
            + question
            + " », je recommande de respecter les règles de clearance IPC-2221, "
            "de contrôler l'impédance des lignes rapides, de découpler chaque pin "
            "d'alimentation (100 nF) et de vérifier la thermique avant export."
        )


class OpenAIProvider:
    """Provider OpenAI (lazy import) — lit OPENAI_API_KEY, base_url surchargeable."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
        self._client: Any = None

    @property
    def model_name(self) -> str:
        return self.model

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI  # dépendance lourde — import lazy
            except ImportError as exc:
                raise RuntimeError(
                    "openai non installé — pip install openai, ou LLM_PROVIDER=mock"
                ) from exc
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        client = self._ensure_client()
        resp = client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""


class ZAIProvider:
    """Provider Z-AI — POST httpx sur endpoint configurable (ZAI_API_BASE)."""

    def __init__(self, model: str | None = None, api_base: str | None = None) -> None:
        self.model = model or os.getenv("ZAI_MODEL", "glm-4-plus")
        self.api_base = api_base or os.getenv("ZAI_API_BASE", "https://api.z.ai/v1")
        self.api_key = os.getenv("ZAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    @property
    def model_name(self) -> str:
        return self.model

    def complete(self, system: str, user: str, temperature: float = 0.2) -> str:
        import httpx  # lazy

        url = f"{self.api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with httpx.Client(timeout=60.0) as cli:
            resp = cli.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""


def get_provider(name: str | None = None) -> LLMProvider:
    """Fabrique de provider selon env LLM_PROVIDER (mock par défaut)."""
    name = (name or os.getenv("LLM_PROVIDER", "mock")).lower()
    if name == "openai":
        try:
            return OpenAIProvider()  # type: ignore[return-value]
        except Exception as exc:
            log.warning("OpenAIProvider indisponible (%s) → fallback mock", exc)
            return MockLLMProvider()
    if name in ("zai", "z-ai", "zhipu"):
        try:
            return ZAIProvider()  # type: ignore[return-value]
        except Exception as exc:
            log.warning("ZAIProvider indisponible (%s) → fallback mock", exc)
            return MockLLMProvider()
    return MockLLMProvider()
