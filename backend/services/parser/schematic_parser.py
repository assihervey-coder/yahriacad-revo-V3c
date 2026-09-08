"""parse_schematic — importe un schéma JSON simple en DesignGraph.

Format attendu :
  {"components": [{"ref", "value", "footprint", "mpn"}...],
   "wires": [["R1", "1", "C1", "2"], ...]                       # [ref1, pad1, ref2, pad2]
           ou [{"from": ["R1", "1"], "to": ["C1", "2"]}...]}

Les fils sont fusionnés par union-find : tout ensemble de pins reliées
(transitivement) devient un net "N1", "N2", ...
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger

from services.design_core.design_graph.components import default_bbox_for_footprint
from services.design_core.design_graph.graph import DesignGraph

log = get_logger("parser.schematic")

Pin = Tuple[str, str]


def _wire_pins(wire: Any) -> Optional[Tuple[Pin, Pin]]:
    """Normalise un fil (liste [ref1,pad1,ref2,pad2] ou dict {from, to})."""
    if isinstance(wire, dict):
        a, b = wire.get("from"), wire.get("to")
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) >= 2 and len(b) >= 2:
            return (str(a[0]), str(a[1])), (str(b[0]), str(b[1]))
        return None
    if isinstance(wire, (list, tuple)) and len(wire) >= 4:
        return (str(wire[0]), str(wire[1])), (str(wire[2]), str(wire[3]))
    return None


class _UnionFind:
    """Union-find minuscule pour regrouper les pins connectées par les fils."""

    def __init__(self) -> None:
        self._parent: Dict[Pin, Pin] = {}

    def find(self, x: Pin) -> Pin:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:            # compression de chemin
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: Pin, b: Pin) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def parse_schematic(json_dict: Dict[str, Any]) -> DesignGraph:
    """Construit un DesignGraph depuis un schéma JSON (composants + fils)."""
    graph = DesignGraph(
        project_id=str(json_dict.get("project_id", "schematic") or "schematic"),
        name=str(json_dict.get("name", "schematic-import") or "schematic-import"),
    )
    for comp in json_dict.get("components", []):
        if not isinstance(comp, dict) or "ref" not in comp:
            continue
        footprint = str(comp.get("footprint", "") or "")
        graph.add_component(
            ref=str(comp["ref"]),
            value=str(comp.get("value", "") or ""),
            footprint=footprint,
            mpn=str(comp.get("mpn", "") or ""),
            bbox=default_bbox_for_footprint(footprint),
        )

    uf = _UnionFind()
    wires = json_dict.get("wires", [])
    for wire in wires:
        pins = _wire_pins(wire)
        if pins is None:
            log.warning("fil ignoré (format invalide): %r", wire)
            continue
        uf.union(*pins)

    groups: Dict[Pin, List[Pin]] = {}
    for wire in wires:
        pins = _wire_pins(wire)
        if pins is None:
            continue
        for pin in pins:
            groups.setdefault(uf.find(pin), []).append(pin)

    # Optionnel : noms de nets fournis {"R1:1": "VCC"} sinon auto "N1", "N2"...
    net_names: Dict[str, str] = json_dict.get("net_names", {})
    for i, (root, pins) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0]), start=1):
        unique_pins = list(dict.fromkeys(pins))
        net_id = f"N{i}"
        graph.add_net(net_id=net_id, name=net_names.get(f"{root[0]}:{root[1]}", net_id))
        for ref, pad in unique_pins:
            if ref not in graph.components:
                graph.add_component(ref=ref)     # composant implicite (schéma minimal)
            graph.connect(ref, pad, net_id)

    log.info("schéma importé : %d composants, %d nets", len(graph.components), len(graph.nets))
    return graph
