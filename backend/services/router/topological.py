"""Topologie des nets — positions de pads, MST, métriques filaires.

Module FONDATION réutilisé par placement_engine, router, simulator et
verification : toute position absolue de pad passe par `pad_position`.
"""
from __future__ import annotations

import math
import re

from shared.geometry import Point
from shared.utilities import get_logger

from services.design_core import Component, DesignGraph, Net, Pad

log = get_logger("router.topological")

# --------------------------------------------------------------------------- classes de nets
POWER_CLASSES = {"power", "pwr", "gnd", "ground"}
HIGH_SPEED_CLASSES = {"high_speed", "highspeed", "hs", "differential", "diff"}


def is_power_net(net: Net) -> bool:
    """True si le net transporte de l'énergie (classe power/gnd ou nom de rail)."""
    cls = (net.class_name or "").lower()
    if cls in POWER_CLASSES:
        return True
    name = (net.name or "").upper().lstrip("+")
    return name.split("_")[0] in {"GND", "AGND", "DGND", "VCC", "VDD", "VSS", "VBAT"} or bool(
        re.match(r"^\d+(\.\d+)?V", name)
    )


def is_high_speed_net(net: Net) -> bool:
    """True si le net est critique en SI (classe, impédance cible ou groupe apparié)."""
    cls = (net.class_name or "").lower()
    if cls in HIGH_SPEED_CLASSES:
        return True
    return net.impedance_target_ohm is not None or net.matched_group is not None


def is_differential_net(net: Net) -> bool:
    """True si le net appartient à une paire différentielle déclarée."""
    return (net.class_name or "").lower() in {"differential", "diff"}


def voltage_of_net(net: Net, default_v: float = 3.3) -> float:
    """Tension nominale déduite du nom du rail ("5V"→5.0, "3V3"→3.3, "1V8"→1.8)."""
    name = (net.name or "").upper()
    m = re.search(r"(\d)(\d)V", name)          # forme compacte 3V3 / 1V8
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*V", name)
    if m:
        return float(m.group(1).replace(",", "."))
    return default_v


def class_rank(net: Net) -> int:
    """Priorité de routage : power/gnd=0, high_speed/differential=1, default=2."""
    if is_power_net(net):
        return 0
    if is_high_speed_net(net):
        return 1
    return 2


# --------------------------------------------------------------------------- pads / positions
def find_pad(comp: Component, pad_name: str) -> Pad | None:
    """Pad `pad_name` d'un composant, None sinon."""
    for p in comp.pads:
        if p.name == pad_name:
            return p
    return None


def pad_position(graph: DesignGraph, ref: str, pad_name: str) -> Point:
    """Position ABSOLUE d'un pad : centre composant + offset tourné (miroir X si bottom).

    Convention unique de la plateforme : Pad.x/y sont relatifs au centre du
    composant, rotation en degrés sens trigonométrique, side="bottom" inverse X.
    """
    comp = graph.get(ref)
    pad = find_pad(comp, pad_name)
    if pad is None:  # pad implicite (netlist minimale) → centre du composant
        return Point(comp.x, comp.y)
    px, py = pad.x, pad.y
    if (comp.side or "top").lower() == "bottom":
        px = -px
    a = math.radians(comp.rotation or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    return Point(comp.x + px * ca - py * sa, comp.y + px * sa + py * ca)


def component_pad_positions(graph: DesignGraph, ref: str) -> list[tuple[str, Point]]:
    """Tous les pads d'un composant : liste (pad_name, position absolue)."""
    return [(p.name, pad_position(graph, ref, p.name)) for p in graph.get(ref).pads]


def net_pad_positions(graph: DesignGraph, net: Net) -> list[tuple[tuple[str, str], Point]]:
    """Positions absolues de tous les pins d'un net : [((ref, pad), Point), ...]."""
    out: list[tuple[tuple[str, str], Point]] = []
    for ref, pad_name in net.pins:
        if ref in graph.components:
            out.append(((ref, pad_name), pad_position(graph, ref, pad_name)))
    return out


# --------------------------------------------------------------------------- MST (Prim maison)
def build_net_topology(graph: DesignGraph, net: Net) -> list[tuple[Point, Point]]:
    """Paires de pads à relier : arbre couvrant minimal (Prim O(n²)) des pins du net.

    Nœuds = positions absolues des pads ; arêtes = distances euclidiennes.
    Retourne la liste des segments (Point, Point) à router.
    """
    nodes = [pos for _, pos in net_pad_positions(graph, net)]
    if len(nodes) < 2:
        return []
    n = len(nodes)
    in_tree = [False] * n
    in_tree[0] = True
    best = [nodes[0].distance_to(p) for p in nodes]   # distance au nœud 0
    best_from = [0] * n
    edges: list[tuple[Point, Point]] = []
    for _ in range(n - 1):
        # plus proche nœud hors arbre
        dmin, j = math.inf, -1
        for k in range(n):
            if not in_tree[k] and best[k] < dmin:
                dmin, j = best[k], k
        if j < 0:
            break
        in_tree[j] = True
        edges.append((nodes[best_from[j]], nodes[j]))
        for k in range(n):
            if not in_tree[k]:
                d = nodes[j].distance_to(nodes[k])
                if d < best[k]:
                    best[k], best_from[k] = d, j
    return edges


def net_length_estimate(graph: DesignGraph, net: Net) -> float:
    """Longueur estimée d'un net : somme des segments du MST (mm)."""
    if net.path is not None:
        return net.path.length()
    return sum(a.distance_to(b) for a, b in build_net_topology(graph, net))


# --------------------------------------------------------------------------- centroïdes / HPWL
def net_centroid(graph: DesignGraph, net: Net) -> Point | None:
    """Centroïde des positions de pads d'un net (None si aucun pin valide)."""
    pads = net_pad_positions(graph, net)
    if not pads:
        return None
    cx = sum(p.x for _, p in pads) / len(pads)
    cy = sum(p.y for _, p in pads) / len(pads)
    return Point(cx, cy)


def hpwl_wire_length(graph: DesignGraph) -> float:
    """Longueur filaire estimée (HPWL étoile) : Σ_nets Σ_pins |pin − centroïde| (mm).

    Métrique de placement indépendante du routage (paths non requis).
    """
    total = 0.0
    for net in graph.nets.values():
        pads = net_pad_positions(graph, net)
        if len(pads) < 2:
            continue
        cx = sum(p.x for _, p in pads) / len(pads)
        cy = sum(p.y for _, p in pads) / len(pads)
        total += sum(math.hypot(p.x - cx, p.y - cy) for _, p in pads)
    return total


def component_nets(graph: DesignGraph, ref: str) -> list[Net]:
    """Nets auxquels participent les pads d'un composant (dédupliqués)."""
    seen: set[str] = set()
    out: list[Net] = []
    for pad in graph.get(ref).pads:
        nid = pad.net_id
        if nid and nid not in seen and nid in graph.nets:
            seen.add(nid)
            out.append(graph.nets[nid])
    return out


# --------------------------------------------------------------------------- keepouts
def keepout_rects(graph: DesignGraph) -> list[tuple[float, float, float, float]]:
    """Keepouts sous forme de rects (min_x, min_y, max_x, max_y) via bbox des polygones."""
    rects: list[tuple[float, float, float, float]] = []
    for k in graph.keepouts or []:
        poly = getattr(k, "polygon", None)
        if poly is None and isinstance(k, (tuple, list)) and len(k) == 4:
            x, y, w, h = k
            rects.append((x, y, x + w, y + h))
            continue
        if poly is None:
            continue
        try:
            (pmin, pmax) = poly.bbox()
            rects.append((pmin.x, pmin.y, pmax.x, pmax.y))
        except Exception:  # polygone dégénéré → ignoré
            continue
    return rects


def rect_hits_keepout(graph: DesignGraph, cx: float, cy: float, w: float, h: float,
                      margin: float = 0.0) -> bool:
    """True si la bbox centrée en (cx, cy) intersecte un keepout (test bbox conservatif)."""
    x0, y0, x1, y1 = cx - w / 2 - margin, cy - h / 2 - margin, cx + w / 2 + margin, cy + h / 2 + margin
    for (kx0, ky0, kx1, ky1) in keepout_rects(graph):
        if not (x1 < kx0 or x0 > kx1 or y1 < ky0 or y0 > ky1):
            return True
    return False


def inside_board(graph: DesignGraph, cx: float, cy: float, w: float, h: float,
                 margin: float = 0.5) -> bool:
    """True si la bbox centrée (cx, cy) tient dans la carte avec `margin` de bord."""
    bw, bh = graph.board_size
    return (cx - w / 2 >= margin and cy - h / 2 >= margin
            and cx + w / 2 <= bw - margin and cy + h / 2 <= bh - margin)


def placement_free(graph: DesignGraph, ref: str, cx: float, cy: float,
                   ignore_side: bool = False) -> bool:
    """Emplacement libre : dans la carte, hors keepouts, sans chevauchement d'autres comps."""
    comp = graph.get(ref)
    w, h = comp.bbox
    if not inside_board(graph, cx, cy, w, h):
        return False
    if rect_hits_keepout(graph, cx, cy, w, h):
        return False
    a0, a1 = cx - w / 2, cx + w / 2
    b0, b1 = cy - h / 2, cy + h / 2
    for other_ref, other in graph.components.items():
        if other_ref == ref or not other.placed:
            continue
        if not ignore_side and (other.side or "top") != (comp.side or "top"):
            continue  # faces opposées : pas de collision 2D
        ow, oh = other.bbox
        ox0, ox1 = other.x - ow / 2, other.x + ow / 2
        oy0, oy1 = other.y - oh / 2, other.y + oh / 2
        if not (a1 <= ox0 or a0 >= ox1 or b1 <= oy0 or b0 >= oy1):
            return False
    return True


def classify_component(comp: Component) -> str:
    """Classe fonctionnelle d'un composant pour le placement par règles.

    Retour : "mount" | "connector" | "mcu" | "power" | "crystal" | "led" |
    "passive" | "other".
    """
    ref = (comp.ref or "").upper()
    value = f"{getattr(comp, 'value', '') or ''} {getattr(comp, 'footprint', '') or ''}".lower()
    full = f"{ref} {value}"
    if ref.startswith(("MH", "H")) and len(ref) <= 4 or "mount" in full or "hole" in full:
        return "mount"
    if "usb" in full or ref.startswith(("J", "CN")) or "conn" in full or "header" in full:
        return "connector"
    if (ref.startswith("U") and len(comp.pads) >= 12) or any(
        k in full for k in ("mcu", "soc", "fpga", "mpu", "dsp")
    ):
        return "mcu"
    if comp.power_w > 0.5 or any(k in full for k in ("reg", "ldo", "buck", "vrm", "dc-dc")):
        return "power"
    if ref.startswith(("Y", "X")) or "xtal" in full or "crystal" in full or "osc" in full:
        return "crystal"
    if ref.startswith("D") or "led" in full:
        return "led"
    if ref.startswith(("R", "C", "L", "FB", "F")):
        return "passive"
    return "other"


def snap(value: float, pitch: float = 2.54) -> float:
    """Arrondit au pas de grille (défaut 2.54 mm)."""
    return round(value / pitch) * pitch


def clamp_to_board(graph: DesignGraph, x: float, y: float, w: float, h: float,
                   margin: float = 1.0) -> tuple[float, float]:
    """Contraint un centre (x, y) pour que la bbox reste dans la carte."""
    bw, bh = graph.board_size
    x = min(max(x, w / 2 + margin), bw - w / 2 - margin)
    y = min(max(y, h / 2 + margin), bh - h / 2 - margin)
    return x, y


def component_pads_on_net(graph: DesignGraph, ref: str, net: Net) -> list[str]:
    """Noms des pads de `ref` qui appartiennent au net `net`."""
    return [pad_name for pin_ref, pad_name in net.pins if pin_ref == ref]
