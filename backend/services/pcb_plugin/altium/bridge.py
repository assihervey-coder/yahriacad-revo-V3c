"""Pont Altium — formats natifs (PCB ASCII, PcbDoc binaire, netlist Protel) + JSON.

Canaux d'échange :
- JSON du pont (`{components, nets}`) : symétrique, rapide, pour les scripts ;
- **PCB 5.0 ASCII** : records `|RECORD=...|` réels d'Altium Designer (géométrie) ;
- **.PcbDoc binaire** (OLE, expérimental, dépendance `olefile`) ;
- **netlist Protel** : connectivité, importable/exportable par quasiment tous
  les outils EDA (Altium Import Wizard, KiCad, ...).

`import_auto()` détecte le format tout seul ; les exports `export_netlist()` /
`export_ascii()` produisent des fichiers ré-importables dans Altium.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from shared.utilities import get_logger

from services.pcb_plugin._compat import _build, core_classes, new_graph
from services.pcb_plugin.altium.formats import (
    is_ole_document,
    payload_to_graph_dict,
)

log = get_logger(__name__)


def _pos_xy(pos: Any) -> tuple[float, float]:
    """Position hétérogène (dict / [x, y] / Point) → (x, y) flottants."""
    if isinstance(pos, dict):
        return float(pos.get("x", 0.0) or 0.0), float(pos.get("y", 0.0) or 0.0)
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    if hasattr(pos, "x"):
        return float(pos.x), float(pos.y)
    return 0.0, 0.0


def _normalize_path_dict(path: dict[str, Any]) -> dict[str, Any]:
    """Normalise un path sérialisé (points/vias hétérogènes) au vocabulaire du pont.

    design_core sérialise points=[[x, y]] et vias=[[[x, y], from, to]] ; le pont
    exposé en dict homogène {x, y} / {x, y, from_layer, to_layer}.
    """
    norm_points: list[dict[str, float]] = []
    for p in path.get("points") or []:
        x, y = _pos_xy(p)
        norm_points.append({"x": x, "y": y})
    path["points"] = norm_points
    norm_vias: list[dict[str, Any]] = []
    for v in path.get("vias") or []:
        if isinstance(v, dict):
            x, y = _pos_xy(v.get("pos", v))
            norm_vias.append({"x": x, "y": y,
                              "from_layer": int(v.get("from_layer", 0) or 0),
                              "to_layer": int(v.get("to_layer", 1) or 1)})
        elif isinstance(v, (list, tuple)) and len(v) >= 3:
            x, y = _pos_xy(v[0])
            norm_vias.append({"x": x, "y": y,
                              "from_layer": int(v[1]), "to_layer": int(v[2])})
    path["vias"] = norm_vias
    return path


class AltiumBridge:
    """Importe/exporte des designs Altium via le format JSON du pont."""

    def __init__(self) -> None:
        self.remote_graph: Any | None = None  # dernier état connu côté Altium

    # -- import ---------------------------------------------------------------
    def import_altium(self, json_path: str) -> Any:
        """Charge un export JSON Altium → DesignGraph."""
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
        graph = self.from_dict(data)
        self.remote_graph = graph
        log.info("Altium importé: %s (%d composants, %d nets)",
                 json_path, len(graph.components), len(graph.nets))
        return graph

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Construit un DesignGraph depuis le dict du pont (champs optionnels remplis)."""
        _, Comp, Net, Pad, Layer, _ = core_classes()
        components: dict[str, Any] = {}
        for cdata in data.get("components") or []:
            cdict = dict(cdata)
            ref = str(cdict.get("ref") or cdict.get("designator") or "")
            if not ref:
                continue
            pads: list[Any] = []
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

        nets: dict[str, Any] = {}
        for ndata in data.get("nets") or []:
            ndict = dict(ndata)
            net_id = str(ndict.get("net_id") or ndict.get("name") or "")
            if not net_id:
                continue
            path_data = ndict.get("path") or {}
            if isinstance(path_data, dict):
                from services.pcb_plugin._compat import route_from_dict
                path = route_from_dict(path_data, net_id)
                ndict["path"] = path  # remplace le dict par le RoutePath réel
            else:
                path = path_data
            ndict.setdefault("net_id", net_id)
            ndict.setdefault("name", net_id)
            ndict.setdefault("class_name", "signal")
            ndict.setdefault("pins", [])
            ndict.setdefault("routed", bool(getattr(path, "points", [])))
            if "path" not in ndict:
                ndict["path"] = path
            ndict.setdefault("impedance_target_ohm", None)
            nets[net_id] = _build(Net, ndict)

        layers = [_build(Layer, ly) if isinstance(ly, dict) else ly
                  for ly in (data.get("layers") or [])]
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
    def export_altium(self, graph: Any) -> dict[str, Any]:
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
                # déjà sérialisé — normalise points/vias au vocabulaire du pont
                net["path"] = _normalize_path_dict(path)
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

    # -- formats natifs Altium -------------------------------------------------
    def import_ascii(self, text: str, name: str = "altium_ascii") -> Any:
        """PCB 5.0 ASCII Altium (records |RECORD=..|) → DesignGraph."""
        from services.pcb_plugin.altium.ascii_pcb import parse_ascii_pcb

        payload = parse_ascii_pcb(text)
        graph = self.from_dict(payload_to_graph_dict(payload, name))
        self.remote_graph = graph
        log.info("Altium ASCII importé: %d composants, %d nets",
                 len(graph.components), len(graph.nets))
        return graph

    def import_netlist(self, text: str, name: str = "altium_netlist") -> Any:
        """Netlist Protel/Altium ([ blocs composants, ( blocs nets) → DesignGraph."""
        from services.pcb_plugin.altium.netlist_io import parse_netlist

        payload = parse_netlist(text)
        graph = self.from_dict(payload_to_graph_dict(payload, name))
        self.remote_graph = graph
        log.info("netlist Altium importée: %d composants, %d nets",
                 len(graph.components), len(graph.nets))
        return graph

    def import_pcbdoc(self, path: str, name: str = "altium_pcbdoc") -> Any:
        """.PcbDoc binaire (OLE, expérimental) → DesignGraph."""
        from services.pcb_plugin.altium.pcbdoc import import_pcbdoc

        payload = import_pcbdoc(path)
        graph = self.from_dict(payload_to_graph_dict(payload, name))
        self.remote_graph = graph
        log.info("PcbDoc binaire importé: %d composants, %d nets",
                 len(graph.components), len(graph.nets))
        return graph

    def import_auto(self, content: str | bytes, name: str = "altium_import") -> tuple[Any, str]:
        """Détection automatique du format Altium → (DesignGraph, format).

        Formats reconnus : JSON du pont, PCB 5.0 ASCII, .PcbDoc binaire (bytes
        OLE ou base64), netlist Protel. Lève ValueError si rien ne correspond.
        """
        raw: bytes | None = None
        if isinstance(content, bytes):
            raw = content
            if is_ole_document(content):
                from services.pcb_plugin.altium.pcbdoc import parse_pcbdoc_stream

                payload = parse_pcbdoc_stream(content)
                graph = self.from_dict(payload_to_graph_dict(payload, name))
                self.remote_graph = graph
                return graph, "pcbdoc"
        text = (content if isinstance(content, str)
                else content.decode("utf-8", errors="replace"))
        stripped = text.strip()
        if not stripped:
            raise ValueError("contenu Altium vide")

        if stripped.startswith("{") or stripped.startswith("["):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                return self.from_dict(data), "json"

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if any(ln.startswith("|RECORD=") for ln in lines):
            return self.import_ascii(text, name), "ascii_pcb"

        if any(ln in ("[", "(") for ln in lines) \
                or any(ln.upper().startswith("*SIGNAL") for ln in lines):
            return self.import_netlist(text, name), "netlist"

        if raw is not None:
            try:
                decoded = base64.b64decode(stripped, validate=True)
            except Exception:
                decoded = b""
            if decoded[:8] and is_ole_document(decoded):
                from services.pcb_plugin.altium.pcbdoc import parse_pcbdoc_stream

                payload = parse_pcbdoc_stream(decoded)
                graph = self.from_dict(payload_to_graph_dict(payload, name))
                self.remote_graph = graph
                return graph, "pcbdoc"
        raise ValueError(
            "format Altium non reconnu (attendu: JSON pont, PCB ASCII, "
            "netlist Protel ou PcbDoc binaire)")

    def export_netlist(self, graph: Any) -> str:
        """DesignGraph → netlist Protel texte (ré-importable dans Altium)."""
        from services.pcb_plugin.altium.netlist_io import write_netlist

        return write_netlist(self.export_altium(graph))

    def export_ascii(self, graph: Any) -> str:
        """DesignGraph → PCB 5.0 ASCII texte (expérimental côté Altium)."""
        from services.pcb_plugin.altium.ascii_pcb import write_ascii_pcb

        return write_ascii_pcb(self.export_altium(graph))
