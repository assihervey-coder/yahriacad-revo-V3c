"""Altium .PcbDoc binaire — lecture expérimentale (OLE compound document).

Un .PcbDoc est un document OLE (Structured Storage) dont le stream
`FileHeader` contient la séquence de records `[2 octets BE longueur][texte
|CLE=VAL|]` — le même vocabulaire que la version ASCII. La connectivité n'est
pas toujours présente dans les champs texte (elle vit dans les données
binaires des records Net) : le parseur extrait donc tout ce qui est fiable
(composants, pads, nets nommés, pistes/vias avec NETNAME) et laisse le pont
compléter la connectivité manquante via une netlist Protel.

Dépendance optionnelle : `olefile` (import paresseux, erreur explicite).
"""
from __future__ import annotations

from typing import Any

from shared.utilities import get_logger

from services.pcb_plugin.altium.formats import (
    layer_info,
    parse_records_binary,
    to_deg,
    to_int,
    to_mm,
)

log = get_logger(__name__)


def extract_fileheader_stream(path: str) -> bytes:
    """Extrait le stream `FileHeader` d'un .PcbDoc (OLE) — exige olefile."""
    try:
        import olefile
    except ImportError as exc:  # dépendance optionnelle
        raise RuntimeError(
            "lecture .PcbDoc binaire : pip install olefile requis") from exc
    with olefile.OleFileIO(path) as ole:
        if not ole.exists("FileHeader"):
            raise ValueError(".PcbDoc sans stream FileHeader (fichier invalide ?)")
        return ole.openstream("FileHeader").read()


def parse_pcbdoc_stream(data: bytes) -> dict[str, Any]:
    """Flux binaire de records → payload intermédiaire (même schéma que l'ASCII)."""
    records = parse_records_binary(data)
    texts = _child_texts(records)

    components: list[dict[str, Any]] = []
    index_to_comp: dict[int, dict[str, Any]] = {}
    nets_by_name: dict[str, dict[str, Any]] = {}
    tracks_by_net: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    vias: list[dict[str, Any]] = []
    xs: list[float] = []
    ys: list[float] = []

    for rec in records:
        rtype = rec.get("RECORD", "")
        if rtype == "2":  # Component
            idx = to_int(rec.get("INDEX"), len(components))
            ref = (rec.get("DESIGNATOR", "").strip()
                   or texts.get(idx, {}).get("designator", "")
                   or f"U{idx + 1}")
            x, y = to_mm(rec.get("X")), to_mm(rec.get("Y"))
            _, side = layer_info(rec.get("LAYER"))
            comp = {
                "ref": ref,
                "value": rec.get("COMMENT", "").strip()
                         or texts.get(idx, {}).get("comment", ""),
                "footprint": rec.get("PATTERN", rec.get("LIBREFERENCE", "")).strip(),
                "x": x, "y": y,
                "rotation": to_deg(rec.get("ROTATION")),
                "side": side,
                "pads": [],
            }
            components.append(comp)
            index_to_comp[idx] = comp
            xs.append(x)
            ys.append(y)
        elif rtype == "8":  # Pad
            target = index_to_comp.get(to_int(rec.get("OWNERINDEX"), -1))
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
            if net_name:
                nets_by_name.setdefault(net_name,
                                        {"net_id": net_name, "name": net_name})
            xs.append(x)
            ys.append(y)
        elif rtype == "27":  # Net
            name = rec.get("NAME", "").strip()
            if name:
                nets_by_name.setdefault(name, {"net_id": name, "name": name})
        elif rtype == "3":  # Track
            net_name = rec.get("NETNAME", "").strip()
            if not net_name:
                continue
            p1 = (to_mm(rec.get("X1")), to_mm(rec.get("Y1")))
            p2 = (to_mm(rec.get("X2")), to_mm(rec.get("Y2")))
            tracks_by_net.setdefault(net_name, []).append((p1, p2))
            nets_by_name.setdefault(net_name, {"net_id": net_name, "name": net_name})
            xs.extend(p1)
            ys.extend(p2)
        elif rtype == "4":  # Via
            net_name = rec.get("NETNAME", "").strip()
            if net_name:
                nets_by_name.setdefault(net_name,
                                        {"net_id": net_name, "name": net_name})
            vias.append({"x": to_mm(rec.get("X")), "y": to_mm(rec.get("Y")),
                         "net_id": net_name})

    nets: list[dict[str, Any]] = []
    for name, net in nets_by_name.items():
        pins = [[c["ref"], str(p.get("name", "?"))]
                for c in components for p in (c.get("pads") or [])
                if str(p.get("net_id", "")) == name]
        segs = tracks_by_net.get(name) or []
        net["pins"] = pins
        net["routed"] = bool(segs)
        if segs:
            points: list[dict[str, float]] = []
            for (x1, y1), (x2, y2) in segs:
                points.append({"x": x1, "y": y1})
                points.append({"x": x2, "y": y2})
            net["path"] = {"net_id": name, "points": points, "layer": 0,
                           "width_mm": 0.2,
                           "vias": [{"x": v["x"], "y": v["y"],
                                     "from_layer": 0, "to_layer": 1}
                                    for v in vias if v.get("net_id") == name]}
        nets.append(net)

    board_w = round((max(xs) - min(xs)) * 1.10 + 6.0, 2) if xs else 50.0
    board_h = round((max(ys) - min(ys)) * 1.10 + 6.0, 2) if ys else 40.0
    return {"components": components, "nets": nets,
            "board_size": [board_w, board_h]}


def import_pcbdoc(path: str) -> dict[str, Any]:
    """Fichier .PcbDoc binaire (OLE) → payload intermédiaire."""
    data = extract_fileheader_stream(path)
    if not data:
        raise ValueError(f"stream FileHeader vide: {path}")
    payload = parse_pcbdoc_stream(data)
    log.info("PcbDoc importé: %s (%d composants, %d nets)",
             path, len(payload["components"]), len(payload["nets"]))
    return payload


def parse_binary_record_sample(data: bytes) -> list[dict[str, str]]:
    """Flux binaire → records bruts (diagnostic : tous les records décodables)."""
    return parse_records_binary(data)


def _child_texts(records: list[dict[str, str]]) -> dict[int, dict[str, str]]:
    from services.pcb_plugin.altium.formats import collect_text_fields
    return collect_text_fields(records)
