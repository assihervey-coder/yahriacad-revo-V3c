"""KG composants — pinout, empreintes compatibles, substituts.

Entrée attendue (`matcher_results`) : liste de dicts, ex :
    {"mpn": "ESP32-WROOM-32E", "package": "MODULE-38", "voltage": 3.3,
     "pinout": {"1": "GND", "2": "3V3", ...},
     "footprints": ["ESP32-WROOM-32x"],
     "substitutes": ["ESP32-WROOM-32D"],
     "interfaces": ["uart", "spi", "i2c"]}
Les clés manquantes sont tolérées ; les nœuds sont id = "comp:<MPN>".
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from shared.utilities import get_logger
from services.ai_engine.knowledge_graph.kg import KnowledgeGraph

log = get_logger("ai_engine.kg.components")

COMP_PREFIX = "comp:"


def build_component_kg(matcher_results: Iterable[Dict[str, Any]]) -> KnowledgeGraph:
    """Construit le KG des composants avec relations pinout / footprint / substitut."""
    kg = KnowledgeGraph()
    results = list(matcher_results)
    for item in results:
        mpn = str(item.get("mpn", "")).strip()
        if not mpn:
            continue
        node_id = COMP_PREFIX + mpn
        kg.add_node(node_id, kind="component", props={
            "mpn": mpn,
            "package": item.get("package", ""),
            "voltage": item.get("voltage"),
            "value": item.get("value", ""),
            "interfaces": item.get("interfaces", []),
        })

        # pinout : relation par pin vers un nœud "signal"
        pinout = item.get("pinout") or {}
        if isinstance(pinout, dict):
            for pin, signal in pinout.items():
                sig_id = f"signal:{signal}"
                kg.add_node(sig_id, kind="signal", props={"name": str(signal)})
                kg.add_edge(node_id, sig_id, "pinout", {"pin": str(pin)})

        # empreintes compatibles
        for fp in item.get("footprints", []) or []:
            fp_id = f"footprint:{fp}"
            kg.add_node(fp_id, kind="footprint", props={"name": str(fp)})
            kg.add_edge(node_id, fp_id, "compatible_footprint", {})

        # substituts (relation symétrique déclarée unidirectionnelle ici)
        for sub in item.get("substitutes", []) or []:
            sub_id = COMP_PREFIX + str(sub)
            kg.add_node(sub_id, kind="component", props={"mpn": str(sub)})
            kg.add_edge(node_id, sub_id, "substitute", {})

    log.info("component KG: %d nœuds, %d arêtes", len(kg.nodes), len(kg.edges))
    return kg


def components_with_interface(kg: KnowledgeGraph, interface: str) -> List[str]:
    """Retourne les MPN du KG exposant une interface donnée."""
    out: List[str] = []
    for node in kg.nodes.values():
        if node.kind == "component" and interface.lower() in [
                str(i).lower() for i in node.props.get("interfaces", [])]:
            out.append(node.props.get("mpn", node.id))
    return out
