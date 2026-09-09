"""Parser d'intention — NL → IntentParseResult → IntentGraph.

Deux modes :
1. LLM (si orchestrator fourni) : JSON structuré ;
2. Fallback heuristique riche (regex/mots-clés) — déterministe, sans dépendance.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

from services.ai_engine._dc_bridge import intent_graph_cls
from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator

log = get_logger("ai_engine.llm.intent_parser")

PROJECT_TYPES = ("iot_sensor", "mcu_board", "power", "rf", "generic")


@dataclass
class IntentParseResult:
    """Résultat de parsing d'intention utilisateur."""

    raw: str
    project_type: str = "generic"
    layers: int = 2
    board_size: tuple[float, float] | None = None
    component_hints: list[str] = field(default_factory=list)
    constraints_text: list[str] = field(default_factory=list)
    target_factory: str | None = None
    priority_goals: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        """Sérialisation compatible JSON."""
        return {
            "raw": self.raw,
            "project_type": self.project_type,
            "layers": self.layers,
            "board_size": list(self.board_size) if self.board_size else None,
            "component_hints": self.component_hints,
            "constraints_text": self.constraints_text,
            "target_factory": self.target_factory,
            "priority_goals": self.priority_goals,
            "confidence": self.confidence,
        }


_TYPE_KEYWORDS = {
    "iot_sensor": ("esp32", "esp8266", "capteur", "sensor", "iot", "ble",
                   "wifi", "zigbee", "lora-node", "température", "humidity"),
    "mcu_board": ("stm32", "mcu", "microcontrôleur", "microcontroller",
                  "devboard", "carte de dev", "rp2040", "pic"),
    "power": ("alimentation", "alim", "power", "ldo", "buck", "boost",
              "convertisseur", "chargeur", "batterie", "12v", "24v"),
    "rf": ("rf", "antenne", "antenna", "lora", "gps", "433mhz", "868mhz",
           "sub-ghz", "front-end"),
}

_COMPONENT_HINTS = (
    "esp32", "esp8266", "stm32", "rp2040", "usb-c", "usb", "capteur",
    "sensor", "imu", "oled", "display", "écran", "sd card", "microsd",
    "ldo", "buck", "led", "bouton", "button", "relais", "relay",
    "lora", "gps", "batterie", "battery", "can", "rs485", "ethernet",
)

_CONSTRAINT_PATTERNS = [
    r"imp[ée]dance\s*\d+\s*[oωΩohm]+[^,.]*",
    r"\d+\s*couches?[^,.]*",
    r"\d+\s*layers?[^,.]*",
    r"length\s*match[^,.]*",
    r"appair[ée][^.]*",
    r"matched[^,.]*",
    r"thermique[^,.]*",
    r"blindage[^,.]*",
    r"shielding[^,.]*",
    r"emi[^,.]*",
    r"cout? minim[ae][^,.]*",
    r"low\s*cost[^,.]*",
]

_FACTORY_KEYWORDS = {"jlcpcb": "jlcpcb", "pcbway": "pcbway"}

_GOAL_KEYWORDS = {
    "coût": ("coût", "cout", "cheap", "low cost", "budget"),
    "miniaturisation": ("petit", "compact", "miniature", "petite"),
    "fiabilité": ("fiable", "fiabilité", "robuste", "industriel"),
    "performance": ("rapide", "performance", "haut débit", "high speed"),
    "manufacturabilité": ("jlcpcb", "pcbway", "assemblage", "manufacture"),
}


class IntentParser:
    """Parse une demande en langage naturel vers une intention structurée."""

    def __init__(self, orchestrator: LLMOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator

    # ---------------------------------------------------------------- parse
    def parse(self, text: str) -> IntentParseResult:
        """Parse `text` : LLM si dispo, sinon/ainsi heuristique riche."""
        base = self._heuristic_parse(text)
        if self.orchestrator is None:
            return base
        try:
            refined = self._llm_parse(text)
        except Exception as exc:
            log.warning("parse LLM échoué (%s) → heuristique", exc)
            return base
        return self._merge(base, refined)

    # ----------------------------------------------------------- heuristique
    def _heuristic_parse(self, text: str) -> IntentParseResult:
        low = text.lower()
        result = IntentParseResult(raw=text)

        # type de projet
        scores = {t: sum(1 for kw in kws if kw in low)
                  for t, kws in _TYPE_KEYWORDS.items()}
        best = max(scores, key=lambda t: scores[t])
        if scores[best] > 0:
            result.project_type = best
            result.confidence = min(0.9, 0.55 + 0.1 * scores[best])

        # couches
        m = re.search(r"(\d+)\s*(?:couches?|layers?|layer|layer-?pcb)", low)
        if m:
            result.layers = max(1, min(32, int(m.group(1))))
            result.constraints_text.append(f"{result.layers} couches")
        m = re.search(r"(?:single|double)\s*(?:sided|layer|couche)", low)
        if m:
            result.layers = 1 if m.group(0).startswith("single") else 2

        # dimensions "60x40mm"
        m = re.search(
            r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(?:mm|millim[èe]tres?)?",
            low)
        if m:
            w = float(m.group(1).replace(",", "."))
            h = float(m.group(2).replace(",", "."))
            if 5 <= w <= 2000 and 5 <= h <= 2000:
                result.board_size = (w, h)

        # composants
        hints = [kw for kw in _COMPONENT_HINTS if kw in low]
        result.component_hints = sorted(set(hints))

        # contraintes textuelles
        for pat in _CONSTRAINT_PATTERNS:
            for m2 in re.finditer(pat, low):
                snippet = m2.group(0).strip()
                if snippet and snippet not in result.constraints_text:
                    result.constraints_text.append(snippet)

        # usine cible
        for kw, factory in _FACTORY_KEYWORDS.items():
            if kw in low:
                result.target_factory = factory
                break

        # objectifs prioritaires
        for goal, kws in _GOAL_KEYWORDS.items():
            if any(kw in low for kw in kws):
                result.priority_goals.append(goal)
        if not result.priority_goals:
            result.priority_goals = ["fiabilité", "manufacturabilité"]

        # confiance : bonus par signal détecté
        signals = sum([
            bool(result.board_size), bool(result.component_hints),
            result.layers != 2 or "couches" in low,
            result.target_factory is not None,
            bool(result.constraints_text),
        ])
        result.confidence = min(0.95, 0.35 + 0.13 * signals
                                + (0.1 if scores[best] > 0 else 0.0))
        return result

    # ------------------------------------------------------------------ LLM
    def _llm_parse(self, text: str) -> IntentParseResult | None:
        assert self.orchestrator is not None
        raw = self.orchestrator.ask(
            question=text,
            system=(
                "Tu es un parseur d'intention EDA. Renvoie UNIQUEMENT un JSON "
                'avec les clés: project_type ("iot_sensor"|"mcu_board"|"power"|"rf"'
                '|"generic"), layers (int), board_size ([w,h] mm ou null), '
                "component_hints (liste), constraints_text (liste), "
                'target_factory ("jlcpcb"|"pcbway"|null), priority_goals (liste), '
                "confidence (0..1)."
            ),
            temperature=0.1,
        )
        txt = raw.strip()
        if txt.startswith("```"):
            txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt)
        data = json.loads(txt)
        if not isinstance(data, dict):
            return None
        size = data.get("board_size")
        return IntentParseResult(
            raw=text,
            project_type=data.get("project_type", "generic")
            if data.get("project_type") in PROJECT_TYPES else "generic",
            layers=int(data.get("layers", 2)),
            board_size=(float(size[0]), float(size[1]))
            if size and len(size) == 2 else None,
            component_hints=[str(x) for x in data.get("component_hints", [])],
            constraints_text=[str(x) for x in data.get("constraints_text", [])],
            target_factory=data.get("target_factory")
            if data.get("target_factory") in _FACTORY_KEYWORDS.values() else None,
            priority_goals=[str(x) for x in data.get("priority_goals", [])],
            confidence=float(data.get("confidence", 0.6)),
        )

    # ---------------------------------------------------------------- merge
    @staticmethod
    def _merge(base: IntentParseResult,
               refined: IntentParseResult | None) -> IntentParseResult:
        """Fusionne heuristique + LLM (l'heuristique complète les trous)."""
        if refined is None:
            return base
        refined.component_hints = sorted(
            set(refined.component_hints) | set(base.component_hints))
        refined.constraints_text = sorted(
            set(refined.constraints_text) | set(base.constraints_text))
        if refined.board_size is None:
            refined.board_size = base.board_size
        if refined.target_factory is None:
            refined.target_factory = base.target_factory
        if not refined.priority_goals:
            refined.priority_goals = base.priority_goals
        refined.confidence = min(0.98, max(refined.confidence, base.confidence) + 0.05)
        return refined


def to_intent_graph(result: IntentParseResult):
    """Convertit un IntentParseResult en IntentGraph (services.design_core).

    Racine = objectif global (priority 1), enfants = sous-intentions typées
    (constraints, functional) avec métadonnées.
    """
    IntentGraph = intent_graph_cls()
    graph = IntentGraph()
    root_goal = (
        f"Concevoir une carte {result.project_type} "
        f"({result.layers} couches"
        + (f", {result.board_size[0]:.0f}x{result.board_size[1]:.0f}mm"
           if result.board_size else "") + ")"
    )
    root = graph.add_intent(root_goal, kind="functional", priority=1)

    def _add(label: str, kind: str, payload: dict[str, Any]) -> None:
        graph.add_intent(label, kind=kind, priority=3, parent_id=root.id,
                         metadata=payload)

    _add(f"Type de projet : {result.project_type}", "functional",
         {"value": result.project_type})
    _add(f"{result.layers} couches", "constraint", {"value": result.layers})
    if result.board_size:
        _add(f"Dimensions {result.board_size[0]:.0f}x{result.board_size[1]:.0f} mm",
             "constraint", {"w": result.board_size[0], "h": result.board_size[1]})
    if result.component_hints:
        _add("Composants : " + ", ".join(result.component_hints), "functional",
             {"hints": result.component_hints})
    for cst in result.constraints_text[:6]:
        _add(f"Contrainte : {cst}", "constraint", {"text": cst})
    if result.target_factory:
        _add(f"Usine cible : {result.target_factory}", "business",
             {"value": result.target_factory})
    for goal in result.priority_goals[:4]:
        _add(f"Objectif prioritaire : {goal}", "quality", {"value": goal})
    return graph


def get_intent_parser() -> IntentParser:
    """Parser singleton avec orchestrateur par défaut (mock)."""
    return IntentParser(orchestrator=None)
