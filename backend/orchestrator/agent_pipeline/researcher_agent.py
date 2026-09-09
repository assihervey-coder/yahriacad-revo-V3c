"""ResearcherAgent — RAG sur les composants / datasheets."""
from __future__ import annotations

import json
import re
from typing import Any

from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import call_probe, try_import

# Mots-clés techniques → fiche de connaissances statique (repli hors-RAG)
_KNOWLEDGE: list[dict[str, str]] = [
    {"kw": "esp32", "answer": "ESP32-WROOM-32E: MCU dual-core 240 MHz, WiFi+BT, 38 pads, "
                              "alim 3.3V, ~80-260 mA en TX — prévoir découplage 10µF+100nF et "
                              "antenne en bord de carte (keepout 8mm)."},
    {"kw": "bme680", "answer": "BME680: capteur T°/humidité/pression/gaz, I²C (0x76/0x77) ou SPI, "
                               "alim 1.7-3.6V, 3.5x3.0 mm — tirer SDA/SCL avec 4.7kΩ, prévoir "
                               "un via de masse proche du pad GND."},
    {"kw": "capteur", "answer": "Capteurs: séparer masse analogique/numérique, raccourcir les "
                                "traces I²C/SPI (<50mm), découpler 100nF au plus près de VDD."},
    {"kw": "alimentation|régulateur|ldo", "answer": "Régulation 3.3V: LDO type AMS1117-3.3 ou "
                                                    "ME6211 — condensateurs 22µF entrée/sortie, "
                                                    "plans de masse continus sous le régulateur."},
    {"kw": "2 couches|2 layers|deux couches", "answer": "2 couches: layer 1 signaux + layer 2 "
                                                        "masse pleine recommandé, vias de couture "
                                                        "périphériques, éviter les coupures du plan GND."},
]


class ResearcherAgent(BaseAgent):
    """Étape `research` : répond aux questions composants, enrichit context["research"]."""

    role = AgentRole.RESEARCHER
    description = "Recherche documentaire (RAG) sur les composants et contraintes techniques."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.RESEARCHER, "researcher", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("research", "research_components", "", "delegate")

    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        message = str(context.get("message") or "")
        params = context.get("params") or {}
        question = str(params.get("research_question") or message or "composants du projet")

        answer = ""
        source = "heuristic"
        # 1) RAG engine du cerveau symbolique
        rag_mod = try_import("services.ai_engine.rag_engine", ["RAGEngine"])
        rag_cls = rag_mod.get("RAGEngine")
        if rag_cls is not None:
            try:
                try:
                    rag = rag_cls()
                except TypeError:
                    rag = rag_cls(self.orchestrator)
                raw = (call_probe(rag, "answer", (question,))
                       or call_probe(rag, "query", (question,))
                       or call_probe(rag, "ask", (question,))
                       or call_probe(rag, "search", (question,)))
                if raw:
                    answer = raw if isinstance(raw, str) else json.dumps(raw, default=str, ensure_ascii=False)
                    source = "rag"
            except Exception as exc:
                self.log.debug("RAGEngine indisponible: %s", exc)

        # 2) Repli : base de connaissances statique
        if not answer:
            lowered = question.lower()
            findings = [entry["answer"] for entry in _KNOWLEDGE
                        if re.search(entry["kw"], lowered)]
            answer = " | ".join(findings) if findings else (
                f"Analyse statique de la demande: '{question[:120]}' — sélection de composants "
                "générique (MCU + capteurs + passifs), nets d'alimentation VCC/GND recommandés.")
        answer = answer[:2000]

        research = {
            "question": question[:300],
            "answer": answer,
            "source": source,
        }
        context["research"] = research
        {"sources": [source], "topics": self._topics(question)}
        self.record_decision(context, "research", answer[:200], confidence=0.7)
        return self.succeeded(context, research, confidence=0.7 if source == "rag" else 0.55,
                              rationale=f"recherche via {source}")

    def _topics(self, question: str) -> list[str]:
        lowered = question.lower()
        topics = []
        for entry in _KNOWLEDGE:
            if re.search(entry["kw"], lowered):
                topics.append(entry["kw"].split("|")[0])
        return topics[:5]
