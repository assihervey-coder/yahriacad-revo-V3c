"""Import KiCad — netlist s-expression et PCB simplifié .kicad_pcb → DesignGraph.

Les pads design_core sont des offsets RELATIFS au centre du composant : les
pads des modules KiCad sont donc stockés tels quels (locale), et les sections
segments/vias reconstruisent les chemins de routage.
"""
from __future__ import annotations

import re
from typing import Any

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

from services.pcb_plugin._compat import _build, new_graph
from services.pcb_plugin.kicad.sexpr import (
    Node,
    SExprParser,
    as_float,
    as_str,
    atom,
    find,
    find_all,
)

log = get_logger(__name__)

_NUM_RE = re.compile(r"(\d+)")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def default_layers() -> list[Any]:
    """Stackup 2 couches par défaut (F.Cu, B.Cu)."""
    _, _, _, _, Layer, _ = _classes()
    out = []
    for idx, name in ((0, "F.Cu"), (1, "B.Cu")):
        out.append(_build(Layer, {
            "index": idx, "name": name, "ltype": "signal",
            "thickness_um": 35.0, "er": 4.4,
        }))
    return out


def _classes() -> tuple[Node, ...]:
    from services.pcb_plugin._compat import core_classes
    return core_classes()


def _natural_key(s: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in _NUM_RE.split(s))


def _power_like(name: str) -> bool:
    up = (name or "").upper()
    return up in {"GND", "AGND", "PGND", "VCC", "VDD", "VSS", "AVDD", "AVCC", "VBAT",
                  "VBUS", "VIN", "V+", "V-"} or up.startswith("+") or "POWER" in up


# ---------------------------------------------------------------------------
# Netlist
# ---------------------------------------------------------------------------

def import_kicad_netlist(text: str) -> Any:
    """Parse une netlist s-expression KiCad → DesignGraph (composants + nets).

    Pas de géométrie dans une netlist : placement en grille et pads génériques
    (une rangée de plots au pas 1.27 mm), nets reliés aux pins.
    """
    DG, Comp, Net, Pad, _Layer, _ = _classes()
    root = SExprParser(text).parse()
    top = root[0] if root and isinstance(root[0], list) else root

    components: dict[str, Node] = {}
    pin_net: dict[tuple[str, str], str] = {}

    for comp in find_all(find(top, "components") or [], "comp"):
        ref = as_str(atom(comp, "ref"), "")
        if not ref:
            continue
        value = as_str(atom(comp, "value"), "")
        footprint = as_str(atom(comp, "footprint"), "")
        mpn = ""
        for prop in find_all(comp, "property"):
            # formes supportées : (property (name "MPN") (value "..."))
            # et (property "MPN" "...")
            if len(prop) > 1 and isinstance(prop[1], str):
                pname = as_str(prop[1], "")
                pvalue = as_str(prop[2] if len(prop) > 2 else "", "")
            else:
                name_node, value_node = find(prop, "name"), find(prop, "value")
                pname = as_str(name_node[1]) if name_node and len(name_node) > 1 else ""
                pvalue = as_str(value_node[1]) if value_node and len(value_node) > 1 else ""
            if pname.upper() in {"MPN", "MANUFACTURER_PN", "MFR_PN"}:
                mpn = pvalue
        components[ref] = {"ref": ref, "value": value, "footprint": footprint,
                           "mpn": mpn, "x": 0.0, "y": 0.0, "rotation": 0.0,
                           "side": "top", "power_w": 0.0, "price_usd": 0.0,
                           "pads": []}

    for net_node in find_all(find(top, "nets") or [], "net"):
        name = as_str(atom(net_node, "name"), "").lstrip("/")  # hiérarchie KiCad aplatie
        code = as_str(atom(net_node, "code"), "")
        net_id = name or (f"N{code}" if code else f"N{len(pin_net) + 1}")
        for node in find_all(net_node, "node"):
            ref = as_str(atom(node, "ref"), "")
            pin = as_str(atom(node, "pin"), "")
            if ref and pin:
                pin_net[(ref, pin)] = net_id

    # Nets du graphe : une entrée par net_id détecté
    nets: dict[str, Node] = {}
    for (ref, pin), net_id in sorted(pin_net.items()):
        entry = nets.setdefault(net_id, {"net_id": net_id, "name": net_id,
                                         "class_name": "power" if _power_like(net_id) else "signal",
                                         "pins": [], "routed": False,
                                         "path": None, "impedance_target_ohm": None})
        entry["pins"].append((ref, pin))

    # Pads génériques (rangée centrée, pas 1.27 mm) + placement en grille
    grid, pitch, per_row = 0, 1.27, 5
    for ref in sorted(components, key=_natural_key):
        comp = components[ref]
        pins = sorted({p for (r, p) in pin_net if r == ref}, key=_natural_key)
        n = max(len(pins), 1)
        col, row = grid % per_row, grid // per_row
        grid += 1
        cx, cy = 12.0 + col * 14.0, 10.0 + row * 12.0
        comp["x"], comp["y"] = cx, cy
        bbox_w = max(2.0, n * pitch + 1.6)
        comp["bbox"] = (bbox_w, 2.4)
        pads = []
        for i, pin in enumerate(pins):
            # design_core : pad.x/y = offset LOCAL au centre du composant
            px = (i - (n - 1) / 2.0) * pitch
            pads.append(_build(Pad, {"name": pin, "x": round(px, 6), "y": 0.0,
                                     "w": 0.6, "h": 0.6,
                                     "net_id": pin_net.get((ref, pin), ""),
                                     "layer": 0}))
        comp["pads"] = pads

    graph = new_graph(
        project_id="kicad-import",
        name="kicad_netlist_import",
        board_size=(max(40.0, 14.0 * min(len(components), per_row) + 6.0),
                    max(30.0, 12.0 * (grid // per_row + 1) + 6.0)),
        components={ref: _build(Comp, c) for ref, c in components.items()},
        nets={nid: _build(Net, {**n, "path": RoutePath(net_id=nid, points=[],
                                                       layer=0, width_mm=0.2, vias=[]),
                                "pins": [tuple(p) for p in n["pins"]]})
              for nid, n in nets.items()},
        layers=default_layers(),
    )
    log.info("netlist KiCad importée: %d composants, %d nets",
             len(components), len(nets))
    return graph


# ---------------------------------------------------------------------------
# PCB
# ---------------------------------------------------------------------------

def _copper_layers(top: Node) -> list[tuple[int, str]]:
    """Couches cuivre déclarées [(id_kicad, nom)] triées par id (0..31 = cuivre)."""
    layers_sec = find(top, "layers") or []
    copper: list[tuple[int, str]] = []
    for entry in layers_sec:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        lid, lname = entry[0], as_str(entry[1])
        if isinstance(lid, int) and 0 <= lid <= 31:
            copper.append((lid, lname))
    return sorted(copper)


def _layer_index_map(top: Node) -> dict[str, int]:
    """nom KiCad → index dense dans le DesignGraph (F.Cu=0 ... B.Cu=n-1)."""
    copper = _copper_layers(top)
    if not copper:
        return {"F.Cu": 0, "B.Cu": 1}
    return {name: i for i, (_kid, name) in enumerate(copper)}


def _chain_segments(segs: list[tuple[Point, Point]], eps: float = 1e-3) -> list[list[Point]]:
    """Chaîne gloutonne de segments → polylignes (simplification assumée)."""
    remaining = [list(s) for s in segs]
    chains: list[list[Point]] = []

    def close(a: Point, b: Point) -> bool:
        return abs(a.x - b.x) < eps and abs(a.y - b.y) < eps

    while remaining:
        a, b = remaining.pop(0)
        chain = [a, b]
        changed = True
        while changed:
            changed = False
            for seg in list(remaining):
                p1, p2 = seg
                if close(chain[-1], p1):
                    chain.append(p2)
                    remaining.remove(seg)
                    changed = True
                elif close(chain[-1], p2):
                    chain.append(p1)
                    remaining.remove(seg)
                    changed = True
                elif close(chain[0], p2):
                    chain.insert(0, p1)
                    remaining.remove(seg)
                    changed = True
                elif close(chain[0], p1):
                    chain.insert(0, p2)
                    remaining.remove(seg)
                    changed = True
        chains.append(chain)
    return chains


def import_kicad_pcb(text: str) -> Node:
    """Parse un .kicad_pcb SIMPLIFIÉ → DesignGraph (modules, pads, segments, vias)."""
    DG, Comp, Net, Pad, Layer, _ = _classes()
    root = SExprParser(text).parse()
    top = root[0] if root and isinstance(root[0], list) else root

    li_map = _layer_index_map(top)

    # --- Taille de carte : contours Edge.Cuts sinon extent des modules
    board_w = board_h = 0.0
    for gr in find_all(top, "gr_line"):
        if as_str(atom(gr, "layer"), "") == "Edge.Cuts":
            s, e = find(gr, "start"), find(gr, "end")
            if s and e:
                board_w = max(board_w, as_float(s[1]) if len(s) > 1 else 0.0,
                              as_float(e[1]) if len(e) > 1 else 0.0)
                board_h = max(board_h, as_float(s[2]) if len(s) > 2 else 0.0,
                              as_float(e[2]) if len(e) > 2 else 0.0)

    components: dict[str, Node] = {}
    # ref → {pin: net_id} pour reconstruire les pins des nets
    pad_net: dict[tuple[str, str], str] = {}
    net_names: dict[int, str] = {}
    segs_by_net: dict[int, list[tuple[Point, Point, float, str]]] = {}
    vias_by_net: dict[int, list[tuple[Point, int, int]]] = {}

    # --- Modules / footprints
    for mod in find_all(top, "module") + find_all(top, "footprint"):
        fp_name = as_str(mod[1] if len(mod) > 1 else "", "unknown:unknown")
        mod_layer = as_str(atom(mod, "layer"), "F.Cu")
        at = find(mod, "at") or []
        cx = as_float(at[1]) if len(at) > 1 else 0.0
        cy = as_float(at[2]) if len(at) > 2 else 0.0
        rot = as_float(at[3]) if len(at) > 3 else 0.0

        ref, value, mpn = "", "", ""
        for ft in find_all(mod, "fp_text"):
            kind = as_str(ft[1] if len(ft) > 1 else "")
            txt = as_str(ft[2] if len(ft) > 2 else "")
            if kind == "reference":
                ref = txt
            elif kind == "value":
                value = txt
        for prop in find_all(mod, "property"):
            pname = as_str(prop[1] if len(prop) > 1 else "").upper()
            if pname in {"REF", "REFERENCE"} and not ref:
                ref = as_str(prop[2] if len(prop) > 2 else "")
            elif pname == "MPN":
                mpn = as_str(prop[2] if len(prop) > 2 else "")
        if not ref:
            ref = f"X{len(components) + 1}"
            log.warning("module sans référence (%s) → %s", fp_name, ref)

        pads: list[Node] = []
        xs: list[float] = []
        ys: list[float] = []
        for pad in find_all(mod, "pad"):
            pname = as_str(pad[1] if len(pad) > 1 else "", f"p{len(pads) + 1}")
            pat = find(pad, "at") or []
            lx = as_float(pat[1]) if len(pat) > 1 else 0.0
            ly = as_float(pat[2]) if len(pat) > 2 else 0.0
            size = find(pad, "size") or []
            pw = as_float(size[1], 0.6) if len(size) > 1 else 0.6
            ph = as_float(size[2], 0.6) if len(size) > 2 else 0.6
            # design_core : pad.x/y = offset local au centre du module (KiCad idem)
            layers_node = find(pad, "layers") or []
            layer_names = [as_str(v) for v in layers_node[1:] if isinstance(v, str)]
            copper_names = [nm for nm in layer_names if nm.endswith(".Cu")]
            pad_layer = li_map.get(copper_names[0], 0) if copper_names else 0
            net = find(pad, "net") or []
            net_num = int(net[1]) if len(net) > 1 and isinstance(net[1], int) else 0
            net_name = as_str(net[2] if len(net) > 2 else "")
            if net_num:
                net_names[net_num] = net_name or net_names.get(net_num, f"N{net_num}")
            net_id = net_names.get(net_num, "") if net_num else ""
            pads.append(_build(Pad, {
                "name": pname, "x": round(lx, 6), "y": round(ly, 6),
                "w": pw, "h": ph, "net_id": net_id, "layer": pad_layer,
            }))
            if net_id:
                pad_net[(ref, pname)] = net_id
            xs += [lx - pw / 2, lx + pw / 2]
            ys += [ly - ph / 2, ly + ph / 2]

        if xs:
            bbox_w = max(1.0, (max(xs) - min(xs)) + 0.8)
            bbox_h = max(1.0, (max(ys) - min(ys)) + 0.8)
        else:
            bbox_w = bbox_h = 2.0
        board_w = max(board_w, cx + bbox_w / 2 + 1.0)
        board_h = max(board_h, cy + bbox_h / 2 + 1.0)
        components[ref] = _build(Comp, {
            "ref": ref, "value": value, "footprint": fp_name, "mpn": mpn,
            "x": cx, "y": cy, "rotation": rot,
            "side": "bottom" if mod_layer == "B.Cu" else "top",
            "bbox": (round(bbox_w, 6), round(bbox_h, 6)),
            "power_w": 0.0, "price_usd": 0.0, "pads": pads,
        })

    # --- Segments de routage
    for seg in find_all(top, "segment"):
        s, e = find(seg, "start"), find(seg, "end")
        if not s or not e:
            continue
        p1 = Point(as_float(s[1]) if len(s) > 1 else 0.0, as_float(s[2]) if len(s) > 2 else 0.0)
        p2 = Point(as_float(e[1]) if len(e) > 1 else 0.0, as_float(e[2]) if len(e) > 2 else 0.0)
        width = as_float(atom(seg, "width"), 0.2)
        lname = as_str(atom(seg, "layer"), "F.Cu")
        net = find(seg, "net") or []
        num = int(net[1]) if len(net) > 1 and isinstance(net[1], int) else 0
        if len(net) > 2 and isinstance(net[2], str) and net[2]:
            net_names[num] = net[2]
        if num <= 0 or lname not in li_map:
            continue
        segs_by_net.setdefault(num, []).append((p1, p2, width, lname))

    # --- Vias
    for via in find_all(top, "via"):
        at = find(via, "at") or []
        pos = Point(as_float(at[1]) if len(at) > 1 else 0.0,
                    as_float(at[2]) if len(at) > 2 else 0.0)
        vlay = find(via, "layers") or []
        names = [as_str(v) for v in vlay[1:] if isinstance(v, str)]
        f_l = li_map.get(names[0] if names else "F.Cu", 0)
        t_l = li_map.get(names[1] if len(names) > 1 else "B.Cu", 1)
        net = find(via, "net") or []
        num = int(net[1]) if len(net) > 1 and isinstance(net[1], int) else 0
        if len(net) > 2 and isinstance(net[2], str) and net[2]:
            net_names[num] = net[2]
        if num > 0:
            vias_by_net.setdefault(num, []).append((pos, f_l, t_l))

    # --- Construction des nets
    nets: dict[str, Node] = {}
    for num, name in sorted(net_names.items()):
        if num <= 0:
            continue
        net_id = name or f"N{num}"
        path = RoutePath(net_id=net_id, points=[], layer=0, width_mm=0.2, vias=[])
        if num in segs_by_net:
            segs = segs_by_net[num]
            chains = _chain_segments([(p1, p2) for p1, p2, _w, _l in segs])
            points: list[Point] = []
            for chain in chains:
                points.extend(chain)
            layer_counts: dict[int, int] = {}
            for _p1, _p2, _w, lname in segs:
                idx = li_map[lname]
                layer_counts[idx] = layer_counts.get(idx, 0) + 1
            layer = max(layer_counts.items(), key=lambda kv: kv[1])[0]
            path = RoutePath(net_id=net_id, points=points, layer=layer,
                             width_mm=segs[0][2], vias=vias_by_net.get(num, []))
        elif num in vias_by_net:
            path = RoutePath(net_id=net_id, points=[], layer=0, width_mm=0.2,
                             vias=vias_by_net[num])
        pins = [k for k in sorted(pad_net) if pad_net[k] == net_id]
        nets[net_id] = _build(Net, {
            "net_id": net_id, "name": net_id,
            "class_name": "power" if _power_like(net_id) else "signal",
            "pins": pins,
            "routed": bool(path.points),
            "path": path,
            "impedance_target_ohm": None,
        })

    # --- Stackup
    copper = _copper_layers(top)
    layers: list[Any] = []
    if copper:
        for i, (_kid, lname) in enumerate(copper):
            ltype = "ground" if lname.upper() in {"GND", "AGND"} else \
                    "power" if lname.upper() in {"PWR", "VCC", "POWER"} else "signal"
            layers.append(_build(Layer, {"index": i, "name": lname, "ltype": ltype,
                                         "thickness_um": 35.0, "er": 4.4}))
    else:
        layers = default_layers()

    graph = new_graph(
        project_id="kicad-import",
        name="kicad_pcb_import",
        board_size=(round(board_w, 6) or 50.0, round(board_h, 6) or 40.0),
        components=components,
        nets=nets,
        layers=layers,
    )
    log.info("PCB KiCad importé: %d composants, %d nets (%d routés)",
             len(components), len(nets), sum(1 for n in nets.values() if n.routed))
    return graph
