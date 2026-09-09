"""Pont Altium — import/export JSON symétrique (format du pont Altium→JSON).

Format attendu : {"components": [...], "nets": [...]} avec, en option,
"layers", "board_size", "project_id", "name" (même vocabulaire que design_core).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.geometry import RoutePath
from shared.utilities import get_logger

from services.pcb_plugin._compat import _build, core_classes, graph_from_dict, new_graph

log = get_logger(__name__)


class AltiumBridge:
    """Importe/exporte des designs Altium via le format JSON du pont."""

    def __init__(self) -> None:
        self.remote_graph: Optional[Any] = None  # dernier état connu côté Altium

    # -- import ---------------------------------------------------------------
    def import_altium(self, json_path: str) -> Any:
        """Charge un export JSON Altium → DesignGraph."""
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        graph = self.from_dict(data)
        self.remote_graph = graph
        log.info("Altium importé: %s (%d composants, %d nets)",
                 json_path, len(graph.components), len(graph.nets))
        return graph

    def from_dict(self, data: Dict[str, Any]) -> Any:
        """Construit un DesignGraph depuis le dict du pont (champs optionnels remplis)."""
        _, Comp, Net, Pad, Layer, _ = core_classes()
        components: Dict[str, Any] = {}
        for cdata in data.get("components") or []:
            cdict = dict(cdata)
            ref = str(cdict.get("ref") or cdict.get("designator") or "")
            if not ref:
                continue
            pads: List[Any] = []
            for p in cdict.get("pads") or []:
                p = dict(p)
                p.setdefault("net_id", "")
                p.setdefault("layer", 0)
                pads.append(_build(Pad, p) if isinstance(p, dict) else p)
            cdict.setdefault("pads", pads)
            for key, default in (("value", ""), ("footprint", ""), ("mpn", ""),
                                 ("x", 0.0), ("y", 0.0), ("rotation", 0.0),
                                 ("side", "top"), ("power_w", 0.0),
                                 ("price_usd", 0.0), ("bbox", (2.0, 2.0))):
                cdict.setdefault(key, default)
            components[ref] = _build(Comp, cdict)

        nets: Dict[str, Any] = {}
        for ndata in data.get("nets") or []:
            ndict = dict(ndata)
            net_id = str(ndict.get("net_id") or ndict.get("name") or "")
            if not net_id:
                continue
            path_data = ndict.get("path") or {}
            if isinstance(path_data, dict):
                from services.pcb_plugin._compat import route_from_dict
                path = route_from_dict(path_data, net_id)
            else:
                path = path_data
            ndict.setdefault("net_id", net_id)
            ndict.setdefault("name", net_id)
            ndict.setdefault("class_name", "signal")
            ndict.setdefault("pins", [])
            ndict.setdefault("routed", bool(getattr(path, "points", [])))
            ndict.setdefault("path", path)
            ndict.setdefault("impedance_target_ohm", None)
            nets[net_id] = _build(Net, ndict)

        layers = [_build(Layer, l) if isinstance(l, dict) else l
                  for l in (data.get("layers") or [])]
        board_size = data.get("board_size") or (50.0, 40.0)
        if isinstance(board_size, dict):
            board_size = (float(board_size.get("w", 50.0)), float(board_size.get("h", 40.0)))
        return new_graph(
            project_id=str(data.get("project_id", "altium-import")),
            name=str(data.get("name", "altium_import")),
            board_size=tuple(board_size)[:2],
            components=components or None,
            nets=nets or None,
            layers=layers or None,
        )

    # -- export ---------------------------------------------------------------
    def export_altium(self, graph: Any) -> Dict[str, Any]:
        """DesignGraph → dict JSON symétrique (importable par import_altium)."""
        from services.pcb_plugin._compat import graph_to_dict
        data = graph_to_dict(graph)
        # symétrisation : listes ordonnées, pads/nets avec le vocabulaire du pont
        # (graph_to_dict peut renvoyer components/nets en listes OU en dicts
        #  selon le backend design_core — les deux formats sont gérés ici)
        raw_components = data.get("components") or {}
        raw_nets = data.get("nets") or {}
        if isinstance(raw_components, dict):
            component_items = [dict(c, ref=str(c.get("ref", ref)))
                               for ref, c in raw_components.items()]
        else:
            component_items = [dict(c) for c in raw_components]
        for comp in component_items:
            comp.setdefault("ref", "")
            pads = comp.get("pads")
            if isinstance(pads, dict):
                comp["pads"] = [dict(p, name=str(p.get("name", name)))
                                for name, p in pads.items()]
        components = component_items

        nets = []
        if isinstance(raw_nets, dict):
            net_items = [dict(n, net_id=str(n.get("net_id", nid)))
                         for nid, n in raw_nets.items()]
        else:
            net_items = [dict(n) for n in raw_nets]
        for net in net_items:
            net.setdefault("net_id", net.get("name", ""))
            path = net.get("path")
            if isinstance(path, dict):
                # déjà sérialisé — normalise les vias si nécessaire
                vias = path.get("vias") or []
                if vias and isinstance(vias[0], (list, tuple)):
                    path["vias"] = [{"x": v[0].x, "y": v[0].y,
                                     "from_layer": v[1], "to_layer": v[2]}
                                    for v in vias]
            elif path is not None and hasattr(path, "points"):
                net["path"] = {
                    "net_id": getattr(path, "net_id", net.get("net_id", "")),
                    "points": [{"x": p.x, "y": p.y} for p in path.points],
                    "layer": int(getattr(path, "layer", 0)),
                    "width_mm": float(getattr(path, "width_mm", 0.2)),
                    "vias": [{"x": v[0].x, "y": v[0].y, "from_layer": v[1],
                              "to_layer": v[2]} for v in getattr(path, "vias", [])],
                }
            nets.append(net)
        payload = {
            "project_id": data.get("project_id", ""),
            "name": data.get("name", ""),
            "board_size": list(data.get("board_size") or (50.0, 40.0)),
            "components": components,
            "nets": nets,
            "layers": data.get("layers", []),
        }
        self.remote_graph = graph
        return payload

    def write_export(self, graph: Any, json_path: str) -> Path:
        """export_altium + écriture disque (raccourci pratique)."""
        payload = self.export_altium(graph)
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out
