"""KG règles électriques — pullups I2C, matching USB, découplage, LDO, etc.

Chaque règle = nœud kind="rule" avec props actionnables (value, unit,
severity) et relations vers les signaux/interfaces concernés.
"""
from __future__ import annotations

from typing import Dict, Iterator, List

from shared.utilities import get_logger
from services.ai_engine.knowledge_graph.kg import KnowledgeGraph

log = get_logger("ai_engine.kg.electrical_rules")

# Règles canoniques (source : datasheets + IPC + notes d'application)
_RULES: List[Dict] = [
    {
        "id": "rule:i2c_pullup", "name": "I2C pull-ups",
        "description": "I2C nécessite des pull-ups 4.7 kΩ sur SDA et SCL (3.3V).",
        "signal": "i2c", "action": "add_pullup", "value": 4.7e3, "unit": "ohm",
        "severity": "error",
    },
    {
        "id": "rule:usb_length_match", "name": "USB DP/DM length match",
        "description": "USB DP/DM : paire 90 Ω diff, matching de longueur ±0.5 mm.",
        "signal": "usb_dp_dm", "action": "length_match", "value": 0.5, "unit": "mm",
        "severity": "error",
    },
    {
        "id": "rule:decoupling_100nf", "name": "Découplage 100 nF par VDD",
        "description": "100 nF céramique au plus près de chaque pin VDD.",
        "signal": "vdd", "action": "add_decoupling", "value": 100e-9, "unit": "F",
        "severity": "error",
    },
    {
        "id": "rule:ldo_output_cap", "name": "Capacité de sortie LDO 22 µF",
        "description": "LDO : condensateur de sortie 22 µF (stabilité).",
        "signal": "ldo_out", "action": "add_capacitor", "value": 22e-6, "unit": "F",
        "severity": "warning",
    },
    {
        "id": "rule:usb_cc_rd", "name": "USB-C Rd 5.1 kΩ",
        "description": "USB-C device : pull-down 5.1 kΩ sur CC1 et CC2.",
        "signal": "usb_cc", "action": "add_pulldown", "value": 5.1e3, "unit": "ohm",
        "severity": "error",
    },
    {
        "id": "rule:esp32_bulk_cap", "name": "Bulk ESP32 470 µF",
        "description": "WiFi : bulk ≥ 470 µF près du module (pics 500 mA).",
        "signal": "vdd_wifi", "action": "add_bulk", "value": 470e-6, "unit": "F",
        "severity": "warning",
    },
    {
        "id": "rule:crystal_loadcaps", "name": "Condensateurs de charge quartz",
        "description": "Quartz : CL = (CL1*CL2)/(CL1+CL2)+Cstray ≈ datasheet.",
        "signal": "xtal", "action": "add_load_caps", "value": 12e-12, "unit": "F",
        "severity": "warning",
    },
    {
        "id": "rule:ground_plane", "name": "Plan de masse continu",
        "description": "Pas de split de plan sous une ligne rapide (retour courant).",
        "signal": "gnd", "action": "keep_plane_continuous", "value": None,
        "unit": "", "severity": "error",
    },
]


def build_electrical_rules_kg() -> KnowledgeGraph:
    """Construit le KG des règles électriques avec relations vers les signaux."""
    kg = KnowledgeGraph()
    for rule in _RULES:
        kg.add_node(rule["id"], kind="rule", props={
            "name": rule["name"],
            "description": rule["description"],
            "action": rule["action"],
            "value": rule["value"],
            "unit": rule["unit"],
            "severity": rule["severity"],
        })
        sig_id = f"signal:{rule['signal']}"
        kg.add_node(sig_id, kind="signal", props={"name": rule["signal"]})
        kg.add_edge(rule["id"], sig_id, "applies_to", {})
    log.info("electrical rules KG: %d règles", len(_RULES))
    return kg


def iter_rules(kg: KnowledgeGraph, signal: str | None = None) -> Iterator[Dict]:
    """Itère les règles du KG, éventuellement filtrées par signal."""
    for node in kg.nodes.values():
        if node.kind != "rule":
            continue
        if signal is not None:
            targets = kg.neighbors(node.id, relation="applies_to")
            if f"signal:{signal}" not in targets:
                continue
        yield node.props | {"id": node.id}


def rules_for_signal(kg: KnowledgeGraph, signal: str) -> List[Dict]:
    """Liste des règles applicables à un signal donné."""
    return list(iter_rules(kg, signal=signal))
