"""KG manufacturiers — usines + capacités (min trace, min hole, couches)."""
from __future__ import annotations

from typing import Any

from shared.utilities import get_logger

from services.ai_engine.knowledge_graph.kg import KnowledgeGraph

log = get_logger("ai_engine.kg.manufacturing")

DEFAULT_PROFILES: list[dict[str, Any]] = [
    {
        "name": "JLCPCB", "min_trace_mm": 0.09, "min_hole_mm": 0.15,
        "max_layers": 20, "min_spacing_mm": 0.09, "max_copper_oz": 3,
        "min_annular_ring_mm": 0.125, "board_thickness_mm": [0.4, 2.0],
    },
    {
        "name": "PCBWay", "min_trace_mm": 0.075, "min_hole_mm": 0.15,
        "max_layers": 32, "min_spacing_mm": 0.075, "max_copper_oz": 6,
        "min_annular_ring_mm": 0.1, "board_thickness_mm": [0.2, 3.2],
    },
]


def build_manufacturing_kg(profiles: list[dict[str, Any]] | None = None) -> KnowledgeGraph:
    """Construit le KG des usines : nœuds factory + relations capability."""
    profiles = profiles or DEFAULT_PROFILES
    kg = KnowledgeGraph()
    for prof in profiles:
        name = str(prof.get("name", "factory")).strip()
        fid = f"factory:{name}"
        kg.add_node(fid, kind="factory", props={
            "name": name,
            "board_thickness_mm": prof.get("board_thickness_mm", [0.4, 2.0]),
            "max_copper_oz": prof.get("max_copper_oz", 2),
            "min_annular_ring_mm": prof.get("min_annular_ring_mm", 0.125),
        })
        cap_specs = [
            (f"{fid}:min_trace", "min_trace", prof.get("min_trace_mm", 0.127), "mm"),
            (f"{fid}:min_hole", "min_hole", prof.get("min_hole_mm", 0.2), "mm"),
            (f"{fid}:min_spacing", "min_spacing", prof.get("min_spacing_mm", 0.127), "mm"),
            (f"{fid}:layers_max", "layers_max", prof.get("max_layers", 14), "count"),
        ]
        for cap_id, key, value, unit in cap_specs:
            kg.add_node(cap_id, kind="capability", props={
                "key": key, "value": value, "unit": unit})
            kg.add_edge(fid, cap_id, "capability", {"key": key, "value": value})

    log.info("manufacturing KG: %d usines", len(profiles))
    return kg


def factory_capabilities(kg: KnowledgeGraph, factory_name: str) -> dict[str, float]:
    """Retourne {min_trace, min_hole, min_spacing, layers_max} d'une usine."""
    fid = f"factory:{factory_name}"
    caps: dict[str, float] = {}
    for e in kg.edges:
        if e.src == fid and e.relation == "capability":
            props = kg.nodes[e.dst].props if e.dst in kg.nodes else e.props
            caps[str(props.get("key", e.dst))] = float(props.get("value", 0) or 0)
    return caps


def check_design_against_factory(kg: KnowledgeGraph, factory_name: str,
                                 design: dict[str, Any]) -> list[str]:
    """Vérifie un design {min_trace_mm, min_hole_mm, layers} contre une usine."""
    caps = factory_capabilities(kg, factory_name)
    issues: list[str] = []
    if design.get("min_trace_mm") and design["min_trace_mm"] < caps.get("min_trace", 0):
        issues.append(f"trace {design['min_trace_mm']}mm < min usine "
                      f"{caps.get('min_trace')}mm ({factory_name})")
    if design.get("min_hole_mm") and design["min_hole_mm"] < caps.get("min_hole", 0):
        issues.append(f"trou {design['min_hole_mm']}mm < min usine "
                      f"{caps.get('min_hole')}mm ({factory_name})")
    if design.get("layers") and design["layers"] > caps.get("layers_max", 99):
        issues.append(f"{design['layers']} couches > max usine "
                      f"{caps.get('layers_max')} ({factory_name})")
    return issues
