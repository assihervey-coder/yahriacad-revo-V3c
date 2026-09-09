"""Export KiCad — DesignGraph → fichier .kicad_pcb texte (version 20221018).

Les pads design_core sont des offsets LOCAUX au centre du composant : ils sont
écrits tels quels dans les modules (convention KiCad), la rotation du pad
correspondant à la rotation du composant. Toutes les coordonnées sont
formatées en mm à 6 décimales.
"""
from __future__ import annotations

import math
from typing import Any

from shared.geometry import Point
from shared.utilities import get_logger

log = get_logger(__name__)

KICAD_VERSION = "20221018"
VIA_SIZE_MM = 0.6
VIA_DRILL_MM = 0.3
EDGE_WIDTH_MM = 0.1


def format_number(value: float) -> str:
    """Formate une valeur mm à 6 décimales (format KiCad)."""
    return f"{float(value):.6f}"


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _q(text: str) -> str:
    return f'"{_esc(text)}"'


def _rotate(p: Point, deg: float) -> Point:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return Point(p.x * c - p.y * s, p.x * s + p.y * c)


def _layer_name(graph: Any, index: int, default: str = "F.Cu") -> str:
    layers = list(getattr(graph, "layers", []) or [])
    for layer in layers:
        if int(getattr(layer, "index", -1)) == index:
            return str(getattr(layer, "name", default))
    if 0 <= index < len(layers):
        return str(getattr(layers[index], "name", default))
    return default


def _kicad_layer_id(name: str, dense_index: int) -> int:
    """Index KiCad officiel (F.Cu=0, In1..=1.., B.Cu=31)."""
    if name == "F.Cu":
        return 0
    if name == "B.Cu":
        return 31
    return max(1, dense_index) if dense_index < 31 else dense_index


def _pad_layers_txt(graph: Any, pad_layer: int) -> tuple[str, str]:
    """(type, clause layers) KiCad pour un pad selon la couche design_core."""
    lname = _layer_name(graph, pad_layer)
    if lname == "F.Cu":
        return "smd", '(layers "F.Cu" "F.Paste" "F.Mask")'
    if lname == "B.Cu":
        return "smd", '(layers "B.Cu" "B.Paste" "B.Mask")'
    return "thru_hole", '(layers "*.Cu" "*.Mask")'


def _net_numbers(graph: Any) -> dict[str, int]:
    return {net_id: i + 1 for i, net_id in enumerate(sorted(graph.nets))}


def _component_module(graph: Any, comp: Any, net_numbers: dict[str, int]) -> str:
    """Bloc (module ...) complet d'un composant, pads transformés par rotation."""
    side = str(getattr(comp, "side", "top") or "top")
    module_layer = "B.Cu" if side == "bottom" else "F.Cu"
    fp = str(getattr(comp, "footprint", "") or "lib:unknown")
    if ":" not in fp:
        fp = f"pcb3:{fp}"
    rot = float(getattr(comp, "rotation", 0.0) or 0.0)
    cx, cy = float(comp.x), float(comp.y)
    ref = str(getattr(comp, "ref", ""))
    value = str(getattr(comp, "value", "") or "")
    silk = "B.SilkS" if side == "bottom" else "F.SilkS"

    lines: list[str] = [
        f'  (module {_q(fp)} (layer {_q(module_layer)}) '
        f'(at {format_number(cx)} {format_number(cy)} {format_number(rot)})',
        f'    (fp_text reference {_q(ref)} (at 0 0 0) (layer {_q(silk)}) '
        f'(effects (font (size 1 1) (thickness 0.15))))',
        f'    (fp_text value {_q(value)} (at 0 0 0) (layer {_q("F.Fab" if side != "bottom" else "B.Fab")}) '
        f'(effects (font (size 1 1) (thickness 0.15))))',
    ]

    for pad in list(getattr(comp, "pads", []) or []):
        pad_name = str(getattr(pad, "name", ""))
        pw, ph = float(pad.w), float(pad.h)
        # design_core : pads = OFFSETS LOCAUX au centre du composant → écrits tels quels
        lx, ly = float(pad.x), float(pad.y)
        layer = int(getattr(pad, "layer", 0) or 0)
        net_id = str(getattr(pad, "net_id", "") or "")
        pad_type, layers_txt = _pad_layers_txt(graph, layer)
        net_txt = ""
        if net_id and net_id in net_numbers:
            net_txt = f' (net {net_numbers[net_id]} {_q(net_id)})'
        lines.append(
            f'    (pad {_q(pad_name)} {pad_type} rect '
            f'(at {format_number(lx)} {format_number(ly)} {format_number(rot)}) '
            f'(size {format_number(pw)} {format_number(ph)}) {layers_txt}{net_txt})'
        )
    lines.append("  )")
    return "\n".join(lines)


def export_kicad_pcb(graph: Any) -> str:
    """Génère un .kicad_pcb VALIDE (modules, segments, vias, contours, nets)."""
    net_numbers = _net_numbers(graph)
    w, h = (float(graph.board_size[0]), float(graph.board_size[1])) \
        if isinstance(graph.board_size, (list, tuple)) else (50.0, 40.0)

    lines: list[str] = [
        f'(kicad_pcb (version {KICAD_VERSION}) (generator "pcb_ai_designer_v3")',
        "  (general (thickness 1.6))",
        '  (paper "A4")',
        "  (layers",
    ]
    for i, layer in enumerate(list(graph.layers or [])):
        name = str(getattr(layer, "name", f"L{i}"))
        lines.append(f'    ({_kicad_layer_id(name, i)} {_q(name)} signal)')
    lines.append("  )")

    lines.append('  (net 0 "")')
    for net_id, num in net_numbers.items():
        lines.append(f'  (net {num} {_q(net_id)})')

    # Modules
    for ref in sorted(graph.components):
        lines.append(_component_module(graph, graph.components[ref], net_numbers))

    # Segments de routage
    for net_id in sorted(graph.nets):
        net = graph.nets[net_id]
        num = net_numbers.get(net_id, 0)
        path = getattr(net, "path", None)
        if path is None or len(getattr(path, "points", [])) < 2:
            continue
        width = float(getattr(path, "width_mm", 0.2))
        layer_name = _layer_name(graph, int(getattr(path, "layer", 0)))
        pts = list(path.points)
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            lines.append(
                f'  (segment (start {format_number(a.x)} {format_number(a.y)}) '
                f'(end {format_number(b.x)} {format_number(b.y)}) '
                f'(width {format_number(width)}) (layer {_q(layer_name)}) (net {num}))'
            )
        for via in list(getattr(path, "vias", []) or []):
            pos = via[0]
            f_idx = int(via[1]) if len(via) > 1 else 0
            t_idx = int(via[2]) if len(via) > 2 else 1
            f_name, t_name = _layer_name(graph, f_idx), _layer_name(graph, t_idx)
            lines.append(
                f'  (via (at {format_number(pos.x)} {format_number(pos.y)}) '
                f'(size {format_number(VIA_SIZE_MM)}) (drill {format_number(VIA_DRILL_MM)}) '
                f'(layers {_q(f_name)} {_q(t_name)}) (net {num}))'
            )

    # Contours Edge.Cuts (rectangle board_size)
    corners = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    for i in range(4):
        x1, y1 = corners[i]
        x2, y2 = corners[i + 1]
        lines.append(
            f'  (gr_line (start {format_number(x1)} {format_number(y1)}) '
            f'(end {format_number(x2)} {format_number(y2)}) '
            f'(layer {_q("Edge.Cuts")}) (width {format_number(EDGE_WIDTH_MM)}))'
        )

    lines.append(")")
    pcb = "\n".join(lines) + "\n"
    log.info("export KiCad: %d modules, %d nets", len(graph.components), len(graph.nets))
    return pcb


def export_kicad_netlist(graph: Any) -> str:
    """Génère une netlist s-expression KiCad (components + nets + nodes).

    Symétrique de import_kicad_netlist : le fichier produit se recharge dans
    la plateforme (ou dans KiCad) sans perte de composants/nets/pins.
    """
    lines: list[str] = [
        '(export (version "E") (design (source "pcb_ai_designer_v3")',
        '  (date "") (tool "PCB_AI_DESIGNER_V3"))',
        "  (components",
    ]
    for ref in sorted(graph.components):
        comp = graph.components[ref]
        value = str(getattr(comp, "value", "") or "")
        fp = str(getattr(comp, "footprint", "") or "")
        mpn = str(getattr(comp, "mpn", "") or "")
        line = f'    (comp (ref {_q(ref)}) (value {_q(value)})'
        if fp:
            line += f' (footprint {_q(fp)})'
        if mpn:
            line += f' (property (name MPN) (value {_q(mpn)}))'
        line += ')'
        lines.append(line)
    lines.append("  )")
    lines.append("  (nets")

    # pins par net depuis les pads des composants
    nets_pins: dict[str, list[tuple]] = {}
    for ref in sorted(graph.components):
        comp = graph.components[ref]
        for pad in list(getattr(comp, "pads", []) or []):
            net_id = str(getattr(pad, "net_id", "") or "")
            if net_id:
                nets_pins.setdefault(net_id, []).append((ref, str(getattr(pad, "name", "") or "")))

    for code, net_id in enumerate(sorted(nets_pins), start=1):
        nodes = "".join(
            f' (node (ref {_q(ref)}) (pin {_q(pin)}))' for ref, pin in nets_pins[net_id])
        lines.append(f'    (net (code {code}) (name {_q(net_id)}){nodes})')
    lines.append("  )")
    lines.append(")")
    out = "\n".join(lines) + "\n"
    log.info("export netlist KiCad: %d composants, %d nets",
             len(graph.components), len(nets_pins))
    return out
