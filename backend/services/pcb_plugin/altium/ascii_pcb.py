"""Altium PCB 5.0 ASCII — lecture/écriture du format records `|RECORD=...|`.

Altium Designer sait sauvegarder une carte en ASCII (Fichier → Sauvegarder une
copie → PCB ASCII File, ou ancien « PCB 5.0 ASCII »). Chaque ligne est un
record `|RECORD=n|CLE=VALEUR|...`. Ce module :

  parse_ascii_pcb(text)  → payload intermédiaire (vocabulaire design_core, mm)
  write_ascii_pcb(graph) → texte ASCII ré-importable dans Altium (expérimental)

Records pris en charge : Board (1), Component (2), Track (3), Via (4),
Text (7, designator/commentaire), Pad (8), Net (27). Les autres records sont
ignorés sans erreur (l'import reste utilisable).
"""
from __future__ import annotations

from typing import Any

from services.pcb_plugin.altium.formats import (
    layer_info,
    mm_to_altium,
    parse_record,
    to_deg,
    to_int,
    to_mm,
)

_PAD_SHAPES = {
    "round": "ROUND", "RECT": "RECTANGULAR", "rect": "RECTANGULAR",
    "octagon": "OCTAGONAL",
}


def _parse_ascii_records(text: str) -> list[dict[str, str]]:
    """Records ASCII : une ligne par record, chaque ligne commence par `|`."""
    records: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            record = parse_record(stripped)
            if record:
                records.append(record)
    return records


def parse_ascii_pcb(text: str) -> dict[str, Any]:
    """PCB ASCII Altium → payload intermédiaire (components/nets en mm).

    Retourne un dict {components, nets, board_size, tracks_par_net, vias}
    compatible `AltiumBridge.from_dict` (via payload_to_graph_dict).
    """
    records = _parse_ascii_records(text)
    texts = _index_child_texts(records)

    components: list[dict[str, Any]] = []
    index_to_comp: dict[int, dict[str, Any]] = {}
    nets_by_name: dict[str, dict[str, Any]] = {}
    tracks_by_net: dict[str, list[dict[str, float]]] = {}
    vias: list[dict[str, Any]] = []
    xs: list[float] = []
    ys: list[float] = []

    for rec in records:
        rtype = rec.get("RECORD", "")
        if rtype == "2":  # Component
            comp_index = to_int(rec.get("INDEX"), len(components))
            ref = (rec.get("DESIGNATOR", "").strip()
                   or texts.get(comp_index, {}).get("designator", ""))
            if not ref:
                ref = f"U{comp_index + 1}"
            x, y = to_mm(rec.get("X")), to_mm(rec.get("Y"))
            _, side = layer_info(rec.get("LAYER"))
            xs.append(x)
            ys.append(y)
            comp_data = {
                "ref": ref,
                "value": (rec.get("COMMENT", "").strip()
                          or texts.get(comp_index, {}).get("comment", "")),
                "footprint": rec.get("PATTERN", rec.get("LIBREFERENCE", "")).strip(),
                "x": x, "y": y,
                "rotation": to_deg(rec.get("ROTATION")),
                "side": side,
                "pads": [],
            }
            components.append(comp_data)
            index_to_comp[comp_index] = comp_data
        elif rtype == "8":  # Pad (enfant de composant)
            owner = to_int(rec.get("OWNERINDEX"), -1)
            target = index_to_comp.get(owner)
            if target is None:
                continue
            x, y = to_mm(rec.get("X")), to_mm(rec.get("Y"))
            net_name = rec.get("NETNAME", "").strip()
            pad_layer, _ = layer_info(rec.get("LAYER"))
            target["pads"].append({
                "name": rec.get("NAME", "").strip() or "?",
                "x": x, "y": y,
                "size": max(to_mm(rec.get("TOPXSIZE")),
                            to_mm(rec.get("TOPYSIZE")), 0.6),
                "layer": pad_layer,
                "net_id": net_name,
            })
            if net_name and net_name not in nets_by_name:
                nets_by_name[net_name] = {"net_id": net_name, "name": net_name}
            xs.append(x)
            ys.append(y)
        elif rtype == "27":  # Net
            name = rec.get("NAME", "").strip()
            if name and name not in nets_by_name:
                nets_by_name[name] = {"net_id": name, "name": name}
        elif rtype == "3":  # Track
            net_name = rec.get("NETNAME", "").strip()
            if not net_name:
                continue
            p1 = (to_mm(rec.get("X1")), to_mm(rec.get("Y1")))
            p2 = (to_mm(rec.get("X2")), to_mm(rec.get("Y2")))
            tracks_by_net.setdefault(net_name, []).append(
                {"x": p1[0], "y": p1[1], "x2": p2[0], "y2": p2[1],
                 "width": max(to_mm(rec.get("WIDTH")), 0.1)})
            nets_by_name.setdefault(net_name, {"net_id": net_name, "name": net_name})
            xs.extend(p1)
            ys.extend(p2)
        elif rtype == "4":  # Via
            net_name = rec.get("NETNAME", "").strip()
            via = {"x": to_mm(rec.get("X")), "y": to_mm(rec.get("Y")),
                   "diameter": max(to_mm(rec.get("DIAMETER")), 0.6),
                   "drill": max(to_mm(rec.get("HOLESIZE")), 0.3),
                   "net_id": net_name}
            vias.append(via)
            if net_name:
                nets_by_name.setdefault(net_name, {"net_id": net_name, "name": net_name})

    # nets : pins depuis les pads + points de piste regroupés
    nets: list[dict[str, Any]] = []
    for name, net in nets_by_name.items():
        pins = _pins_for_net(components, name)
        path: dict[str, Any] | None = None
        segs = tracks_by_net.get(name) or []
        via_list = [v for v in vias if v.get("net_id") == name]
        if segs or via_list:
            points: list[dict[str, float]] = []
            for seg in segs:
                points.append({"x": seg["x"], "y": seg["y"]})
                points.append({"x": seg["x2"], "y": seg["y2"]})
            width = segs[0]["width"] if segs else 0.2
            path = {"net_id": name, "points": points, "layer": 0,
                    "width_mm": width,
                    "vias": [{"x": v["x"], "y": v["y"], "from_layer": 0,
                              "to_layer": 1} for v in via_list]}
        net["pins"] = pins
        net["routed"] = bool(segs)
        if path is not None:
            net["path"] = path
        nets.append(net)

    # taille de carte : étendue des primitives + marge 10 % (defaut 50x40)
    board_w = max(xs) - min(xs) if xs else 50.0
    board_h = max(ys) - min(ys) if ys else 40.0
    if xs:
        board_w = round(board_w * 1.10 + 6.0, 2)
        board_h = round(board_h * 1.10 + 6.0, 2)

    return {
        "components": components,
        "nets": nets,
        "board_size": [board_w, board_h],
        "board_size_from_content": bool(xs),
    }


def _index_child_texts(records: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    from services.pcb_plugin.altium.formats import collect_text_fields
    return collect_text_fields(records)


def _pins_for_net(components: list[dict[str, Any]], net_name: str) -> list[list[str]]:
    """Pins [[ref, pad], ...] d'un net d'après les pads importés."""
    pins: list[list[str]] = []
    for comp in components:
        for pad in comp.get("pads") or []:
            if str(pad.get("net_id", "")) == net_name:
                pins.append([comp["ref"], str(pad.get("name", "?"))])
    return pins


# ------------------------------------------------------------------ écriture
def write_ascii_pcb(payload: dict[str, Any]) -> str:
    """Payload design_core → PCB 5.0 ASCII (ré-importable par le parseur ci-dessus).

    Expérimental côté Altium (l'Import Wizard d'Altium peut rejeter des
    attributs manquants) ; garanti round-trip avec parse_ascii_pcb.
    """
    lines: list[str] = [
        "PCB FILE - Protel for Windows - PCB File Version 5.0",
    ]
    board = payload.get("board_size") or (50.0, 40.0)
    if isinstance(board, dict):
        board = (float(board.get("w", 50.0)), float(board.get("h", 40.0)))
    lines.append(_record(1, [("FILETIME", ""), ("SIZE", mm_to_altium(max(board))) ]))

    for index, comp in enumerate(payload.get("components") or []):
        lines.append(_record(2, [
            ("INDEX", index),
            ("DESIGNATOR", str(comp.get("ref", ""))),
            ("PATTERN", str(comp.get("footprint", ""))),
            ("COMMENT", str(comp.get("value", ""))),
            ("X", mm_to_altium(float(comp.get("x", 0.0)))),
            ("Y", mm_to_altium(float(comp.get("y", 0.0)))),
            ("ROTATION", f"{float(comp.get('rotation', 0.0)):.6f}"),
            ("LAYER", "TOPLAYER" if str(comp.get("side", "top")) != "bottom"
             else "BOTTOMLAYER"),
        ]))
        for pad in comp.get("pads") or []:
            size = mm_to_altium(max(float(pad.get("size", 1.2)), 0.6))
            lines.append(_record(8, [
                ("OWNERINDEX", index),
                ("NAME", str(pad.get("name", "?"))),
                ("X", mm_to_altium(float(pad.get("x", 0.0)))),
                ("Y", mm_to_altium(float(pad.get("y", 0.0)))),
                ("TOPXSIZE", size), ("TOPYSIZE", size),
                ("HOLESIZE", 0),
                ("TOPSHAPE", _PAD_SHAPES.get(str(pad.get("shape", "round")).lower(),
                                             "ROUND")),
                ("LAYER", "TOPLAYER"),
                ("NETNAME", str(pad.get("net_id", "") or "")),
            ]))

    for net in payload.get("nets") or []:
        net_id = str(net.get("net_id", net.get("name", "")))
        if not net_id:
            continue
        lines.append(_record(27, [("NAME", net_id)]))
        path = net.get("path")
        points = (path or {}).get("points") if isinstance(path, dict) else None
        if points and len(points) >= 2:
            width = mm_to_altium(float(path.get("width_mm", 0.2)) or 0.2)
            xy = [_pxy(p) for p in points]
            for (ax, ay), (bx, by) in zip(xy, xy[1:], strict=False):
                lines.append(_record(3, [
                    ("X1", mm_to_altium(ax)),
                    ("Y1", mm_to_altium(ay)),
                    ("X2", mm_to_altium(bx)),
                    ("Y2", mm_to_altium(by)),
                    ("WIDTH", width),
                    ("LAYER", "TOPLAYER"),
                    ("NETNAME", net_id),
                ]))
            for via in path.get("vias") or []:
                pos = via.get("pos", via) if isinstance(via, dict) else via
                vx, vy = _pxy(pos)
                lines.append(_record(4, [
                    ("X", mm_to_altium(vx)), ("Y", mm_to_altium(vy)),
                    ("DIAMETER", mm_to_altium(0.8)), ("HOLESIZE", mm_to_altium(0.4)),
                    ("NETNAME", net_id),
                ]))
    return "\n".join(lines) + "\n"


def _pxy(p: Any) -> tuple[float, float]:
    """Point payload (dict {x, y} ou liste [x, y]) → (x, y)."""
    if isinstance(p, dict):
        return float(p.get("x", 0.0) or 0.0), float(p.get("y", 0.0) or 0.0)
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return float(p[0]), float(p[1])
    return 0.0, 0.0


def _record(rtype: int, fields: list[tuple[str, Any]]) -> str:
    """Construit une ligne record `|RECORD=n|CLE=valeur|...`."""
    parts = [f"RECORD={rtype}"]
    for key, value in fields:
        parts.append(f"{key}={value}")
    return "|" + "|".join(parts) + "|"
