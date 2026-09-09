"""parse_pcb — réimporte un PCB déjà placé/routé (JSON de session) en DesignGraph.

Format canonique = DesignGraph.to_dict() ; tolérances acceptées :
  - "board_size_mm" au lieu de "board_size", clés *_mm,
  - routes séparées au niveau racine : "routes": [{"net_id", "points", "layer", ...}],
  - placements séparés : "placements": [{"ref", "x", "y", "rotation", "side"}].
Sert au re-import de sessions sauvegardées (les RoutePath des nets sont reconstruits).
"""
from __future__ import annotations

import json
from typing import Any

from shared.utilities import get_logger

from services.design_core.design_graph.graph import DesignGraph

log = get_logger("parser.pcb")


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """Ramène les variantes de format vers le dict canonique de DesignGraph.to_dict()."""
    board = data.get("board_size") or data.get("board_size_mm") or [100.0, 80.0]
    canonical: dict[str, Any] = {
        "project_id": str(data.get("project_id", "") or ""),
        "name": str(data.get("name", "pcb-import") or "pcb-import"),
        "board_size": [_as_float(board[0], 100.0), _as_float(board[1], 80.0)],
        "layers": data.get("layers", []),
        "components": [],
        "nets": [],
        "keepouts": data.get("keepouts", []),
    }

    # --- composants : positions éventuelles sous "placements"
    placements = {p.get("ref"): p for p in data.get("placements", []) if isinstance(p, dict)}
    for comp in data.get("components", []):
        if not isinstance(comp, dict):
            continue
        c = dict(comp)
        placement = placements.get(c.get("ref"))
        if placement:
            for key in ("x", "y", "rotation", "side", "placed"):
                c.setdefault(key, placement.get(key))
        # placed implicite dès qu'une position existe
        if "placed" not in c:
            c["placed"] = any(k in comp for k in ("x_mm", "x", "placement"))
        c.setdefault("x", _as_float(c.get("x_mm"), 0.0))
        c.setdefault("y", _as_float(c.get("y_mm"), 0.0))
        c.setdefault("rotation", _as_float(c.get("rotation_deg"), 0.0))
        canonical["components"].append(c)

    # --- nets : path direct, ou routes séparées au niveau racine
    routes_by_net: dict[str, dict[str, Any]] = {}
    for route in data.get("routes", []):
        if isinstance(route, dict) and route.get("net_id"):
            routes_by_net[str(route["net_id"])] = route
    for net in data.get("nets", []):
        if not isinstance(net, dict):
            continue
        n = dict(net)
        if n.get("path") is None and n.get("net_id") in routes_by_net:
            n["path"] = routes_by_net[n["net_id"]]
        canonical["nets"].append(n)

    return canonical


def parse_pcb(text: Any) -> DesignGraph:
    """Charge un PCB (chaîne JSON ou dict déjà parsé) et reconstruit le graphe complet."""
    data = json.loads(text) if isinstance(text, str) else dict(text)
    graph = DesignGraph.from_dict(_normalize(data))
    routed = sum(1 for n in graph.nets.values() if n.routed)
    log.info("PCB réimporté : %d composants, %d nets (%d routés)",
             len(graph.components), len(graph.nets), routed)
    return graph
