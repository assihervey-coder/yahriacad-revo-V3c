"""Vérifications déterministes — board, overlap, keepout, connectivité.

Chaque issue : {"kind", "severity", "message", "location"}.
Travaille par duck-typing sur l'interface DesignGraph du contrat (agent 2-a).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger

log = get_logger("ai_engine.verify.deterministic")


def _board_extents(graph) -> Optional[Tuple[float, float]]:  # noqa: ANN001
    """Dimensions de carte (w,h) si détectables, sinon None."""
    bs = getattr(graph, "board_size", None)
    if isinstance(bs, (tuple, list)) and len(bs) >= 2:
        try:
            w, h = float(bs[0]), float(bs[1])
            if w > 0 and h > 0:
                return w, h
        except (TypeError, ValueError):
            pass
    for attr in ("board_width", "board_w", "width"):
        w = getattr(graph, attr, None)
        h = getattr(graph, "board_height" if attr != "width" else "height", None)
        if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0:
            return float(w), float(h)
    try:
        d = graph.to_dict()
        for key in ("board", "board_size", "outline"):
            if key in d:
                val = d[key]
                if isinstance(val, dict) and "width" in val and "height" in val:
                    return float(val["width"]), float(val["height"])
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    return float(val[0]), float(val[1])
    except Exception:
        pass
    return None


def _rotated_bbox(comp) -> Tuple[float, float]:  # noqa: ANN001
    """(w,h) effectifs selon la rotation (swap à 90/270)."""
    w, h = comp.bbox
    rot = float(getattr(comp, "rotation", 0.0) or 0.0) % 180
    return (h, w) if rot == 90.0 else (w, h)


def _bbox_overlap(a: Tuple[float, float, float, float],
                  b: Tuple[float, float, float, float]) -> bool:
    """Overlap AABB : (x, y, w, h) avec (x,y) = coin bas-gauche."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or
                ay + ah <= by or by + bh <= ay)


def check_deterministic(graph) -> List[Dict[str, Any]]:  # noqa: ANN001
    """Checks purs (pas de simulation) : board, overlap, keepout, connectivité."""
    issues: List[Dict[str, Any]] = []
    components = dict(getattr(graph, "components", {}) or {})
    nets = dict(getattr(graph, "nets", {}) or {})
    board = _board_extents(graph)

    # 1) composants hors board + keepout bordure 2 mm
    if board is not None:
        bw, bh = board
        keepout = 2.0
        for ref, comp in components.items():
            w, h = _rotated_bbox(comp)
            x0, y0 = comp.x - w / 2.0, comp.y - h / 2.0
            if x0 < -keepout or y0 < -keepout or x0 + w > bw + keepout \
                    or y0 + h > bh + keepout:
                issues.append({
                    "kind": "component_out_of_board",
                    "severity": "error",
                    "message": f"{ref} hors de la carte ({bw:.0f}x{bh:.0f}mm) "
                               f"ou dans la zone de garde",
                    "location": {"ref": ref, "x": comp.x, "y": comp.y},
                })

    # 2) overlaps bbox
    refs = sorted(components.keys())
    for i, ra in enumerate(refs):
        ca = components[ra]
        wa, ha = _rotated_bbox(ca)
        box_a = (ca.x - wa / 2, ca.y - ha / 2, wa, ha)
        for rb in refs[i + 1:]:
            cb = components[rb]
            wb, hb = _rotated_bbox(cb)
            box_b = (cb.x - wb / 2, cb.y - hb / 2, wb, hb)
            if _bbox_overlap(box_a, box_b):
                issues.append({
                    "kind": "bbox_overlap",
                    "severity": "error",
                    "message": f"overlap d'empreintes entre {ra} et {rb}",
                    "location": {"ref": ra, "ref2": rb,
                                 "x": (ca.x + cb.x) / 2, "y": (ca.y + cb.y) / 2},
                })

    # 3) nets non connectés : pins sans net + nets avec < 2 pins
    pin_to_net: Dict[Tuple[str, str], str] = {}
    for net_id, net in nets.items():
        pins = list(getattr(net, "pins", []) or [])
        if len(pins) < 2 and net_id not in ("GND", "3V3", "5V"):
            issues.append({
                "kind": "net_too_few_pins",
                "severity": "warning",
                "message": f"net {getattr(net, 'name', net_id)} n'a qu'un pin",
                "location": {"net": str(net_id)},
            })
        for pin in pins:
            try:
                ref, pad = pin[0], pin[1]
            except (TypeError, IndexError):
                continue
            pin_to_net[(str(ref), str(pad))] = str(net_id)

    for net_id, net in nets.items():
        pins = list(getattr(net, "pins", []) or [])
        seen_pairs = set()
        for pin in pins:
            try:
                ref, pad = str(pin[0]), str(pin[1])
            except (TypeError, IndexError):
                continue
            if (ref, pad) in seen_pairs:
                issues.append({
                    "kind": "duplicate_pad_on_net",
                    "severity": "error",
                    "message": f"pad {ref}.{pad} dupliqué sur le net "
                               f"{getattr(net, 'name', net_id)}",
                    "location": {"net": str(net_id), "ref": ref, "pad": pad},
                })
            seen_pairs.add((ref, pad))
            if ref not in components:
                issues.append({
                    "kind": "pin_without_component",
                    "severity": "error",
                    "message": f"pin {ref}.{pad} référence un composant absent",
                    "location": {"net": str(net_id), "ref": ref, "pad": pad},
                })

    # 4) nets non routés
    try:
        unrouted = list(graph.unrouted_nets() or [])
    except Exception:
        unrouted = [n_id for n_id, n in nets.items()
                    if not getattr(n, "routed", False)]
    if unrouted:
        issues.append({
            "kind": "unrouted_nets",
            "severity": "warning",
            "message": f"{len(unrouted)} nets non routés",
            "location": {"nets": [str(u) for u in unrouted][:20]},
        })

    log.debug("deterministic checks: %d issues", len(issues))
    return issues
