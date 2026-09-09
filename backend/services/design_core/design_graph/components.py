"""Composants et pads — briques du design graph (source de vérité)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Empreintes courantes -> (largeur, hauteur) en mm (bbox mécanique incl. pads).
FOOTPRINT_BBOX: Dict[str, Tuple[float, float]] = {
    "0402": (1.0, 0.5),
    "0603": (1.6, 0.8),
    "0805": (2.0, 1.25),
    "1206": (3.2, 1.6),
    "SOT-23": (2.9, 2.4),
    "SOT-223": (6.5, 3.5),
    "SOIC-8": (4.9, 3.9),
    "SOP-8": (4.9, 3.9),
    "SOIC-16": (9.9, 3.9),
    "LQFP-48": (7.0, 7.0),
    "LQFP-64": (10.0, 10.0),
    "QFN-32": (5.0, 5.0),
    "QFN-48": (7.0, 7.0),
    "LGA-8": (3.0, 3.0),
    "ESP32-WROOM": (18.0, 25.5),
    "USB-C": (8.94, 7.35),
    "XTAL-3225": (3.2, 2.5),
    "JST-PH": (8.0, 5.0),
    "TO-220": (10.0, 8.7),
    "DIP-8": (9.2, 6.4),
}

DEFAULT_BBOX: Tuple[float, float] = (1.0, 0.5)

# --- inférence paramétrique par nom d'empreinte (QFN-16, TSSOP-20, BGA-64…)
_RE_PIN_COUNT = re.compile(r"(?:^|[^0-9])(\d{1,3})(?:[^0-9]|$)")
_RE_PITCH = re.compile(r"0\.(5|4|65|8)(?:mm)?\b")


def _infer_bbox_from_name(footprint: str) -> Optional[Tuple[float, float]]:
    """Déduit (w, h) depuis le nom : QFN-16_0.5mm → (4.5, 4.5), TSSOP-20 →
    (6.5, 4.4), BGA-64 → (8.0, 8.0). Retourne None si non déductible."""
    fp = (footprint or "").lower()
    m = _RE_PIN_COUNT.search(fp)
    n = int(m.group(1)) if m else 0
    if n <= 0:
        return None
    mp = _RE_PITCH.search(fp)
    pitch = float(f"0.{mp.group(1)}") if mp else 0.5

    if any(k in fp for k in ("qfn", "dfn", "mlf")):
        per_side = max(2, (n + 3) // 4)
        side = (per_side - 1) * pitch + 2.0        # pads + marge de corps
        return (round(side, 1), round(side, 1))
    if any(k in fp for k in ("qfp", "lqfp", "mqfp")):
        per_side = max(2, (n + 3) // 4)
        side = (per_side - 1) * max(pitch, 0.65) + 2.6
        return (round(side, 1), round(side, 1))
    if "bga" in fp:
        side = max(3.0, math.ceil(math.sqrt(n)) * pitch + 1.5)
        return (round(side, 1), round(side, 1))
    if any(k in fp for k in ("tssop", "ssop", "msop", "sop", "soic", "so")):
        width = 6.5 if "tssop" in fp or "ssop" in fp else 4.9
        family_pitch = 0.65 if ("tssop" in fp or "ssop" in fp or "msop" in fp) else 1.27
        per_row = max(2, (n + 1) // 2)
        length = max(3.9, (per_row - 1) * family_pitch + 2.6)
        return (round(length, 1), round(width - 1.0, 1))
    if "dip" in fp:
        rows = max(2, (n + 1) // 2)
        return (round(max(9.2, (rows - 1) * 2.54 + 2.5), 1), 6.4)
    return None


def default_bbox_for_footprint(footprint: str) -> Tuple[float, float]:
    """Déduit une bbox (w, h) mm plausible à partir du nom d'empreinte.

    Ordre : table explicite → inférence paramétrique (boîtier + nombre de
    pads + pas) → bbox générique.
    """
    fp = (footprint or "").lower()
    for key, bbox in FOOTPRINT_BBOX.items():
        if key.lower() in fp:
            return bbox
    inferred = _infer_bbox_from_name(footprint)
    if inferred is not None:
        return inferred
    return DEFAULT_BBOX


@dataclass
class Pad:
    """Pad d'un composant. x/y sont des offsets RELATIFS au centre du composant (mm)."""

    name: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.6
    h: float = 0.6
    net_id: Optional[str] = None
    layer: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "net_id": self.net_id,
            "layer": self.layer,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Pad":
        return cls(
            name=str(d.get("name", "1")),
            x=float(d.get("x", d.get("x_mm", 0.0)) or 0.0),
            y=float(d.get("y", d.get("y_mm", 0.0)) or 0.0),
            w=float(d.get("w", d.get("width_mm", 0.6)) or 0.6),
            h=float(d.get("h", d.get("height_mm", 0.6)) or 0.6),
            net_id=d.get("net_id"),
            layer=int(d.get("layer", 0) or 0),
        )


@dataclass
class Component:
    """Composant du design : identité (ref/mpn), placement (x, y, rotation), pads."""

    ref: str
    value: str = ""
    footprint: str = ""
    mpn: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0            # degrés
    side: str = "top"                # top | bottom
    bbox: Tuple[float, float] = DEFAULT_BBOX   # (w, h) mm
    power_w: float = 0.0             # dissipation thermique estimée
    price_usd: float = 0.0
    pads: List[Pad] = field(default_factory=list)
    placed: bool = False

    @property
    def width(self) -> float:
        return self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref": self.ref,
            "value": self.value,
            "footprint": self.footprint,
            "mpn": self.mpn,
            "x": self.x,
            "y": self.y,
            "rotation": self.rotation,
            "side": self.side,
            "bbox": [self.bbox[0], self.bbox[1]],
            "power_w": self.power_w,
            "price_usd": self.price_usd,
            "pads": [p.to_dict() for p in self.pads],
            "placed": self.placed,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Component":
        bbox = d.get("bbox") or d.get("bbox_mm") or list(DEFAULT_BBOX)
        fp = str(d.get("footprint", "") or "")
        return cls(
            ref=str(d.get("ref", "U?")),
            value=str(d.get("value", "") or ""),
            footprint=fp,
            mpn=str(d.get("mpn", "") or ""),
            x=float(d.get("x", d.get("x_mm", 0.0)) or 0.0),
            y=float(d.get("y", d.get("y_mm", 0.0)) or 0.0),
            rotation=float(d.get("rotation", d.get("rotation_deg", 0.0)) or 0.0),
            side=str(d.get("side", "top") or "top"),
            bbox=(float(bbox[0]), float(bbox[1])),
            power_w=float(d.get("power_w", 0.0) or 0.0),
            price_usd=float(d.get("price_usd", 0.0) or 0.0),
            pads=[Pad.from_dict(p) for p in d.get("pads", [])],
            placed=bool(d.get("placed", False)),
        )


# ---------------------------------------------------------------------------
# Layout des pads implicites — empreintes courantes
# ---------------------------------------------------------------------------

_CHIP_KEYS = ("0402", "0603", "0805", "1206", "sod", "resistor", "capacitor",
              "inductor", "diode", "led", "r_", "c_", "l_")
_IC_KEYS = ("qfp", "lqfp", "qfn", "lga", "soic", "sop", "tssop", "ssop",
            "msop", "dfn", "sc-70", "sc70")
_MODULE_KEYS = ("wroom", "esp32", "esp-", "nrf", "rn487", "xbee", "module",
                "hc-05", "ble", "lora")
_USB_KEYS = ("usb", "type-c", "typec")
_LINEAR_KEYS = ("to-220", "to220", "to-92", "ams1117", "sot-223", "sot223",
                "sot-89", "sot-23", "sot23", "sot-323", "jst", "ph2", "header",
                "pin", "terminal", "screw", "kf301", "con", "conn")


def implicit_pad_layout(footprint: str, index: int,
                        bbox: Tuple[float, float]) -> Tuple[float, float, float, float]:
    """Position + taille (x, y, w, h) du pad implicite n°``index`` pour l'empreinte.

    Remplace l'ancien pad implicite empilé en (0,0) : les pads créés par
    :meth:`DesignGraph.connect` sont désormais répartis de façon réaliste
    selon la famille d'empreinte (chips 2 pads, IC 2 colonnes, modules
    2 rangées, USB-C en rangée basse, boîtiers linéaires).

    Convention : offsets RELATIFS au centre du composant, en mm.
    """
    w, h = bbox
    fp = (footprint or "").lower()

    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    # --- Chips 2 pads (R / C / L / diodes) : pads aux deux extrémités
    if any(k in fp for k in _CHIP_KEYS) and index <= 1:
        pad_w, pad_h = 0.45, 0.55
        x = -(w / 2 - pad_w / 2 - 0.05) if index == 0 else (w / 2 - pad_w / 2 - 0.05)
        return x, 0.0, pad_w, pad_h

    # --- Connecteurs USB : rangée le long du bord bas
    if any(k in fp for k in _USB_KEYS):
        pitch = 0.5
        x = clamp(-w / 2 + 1.0 + pitch * index, -w / 2 + 0.4, w / 2 - 0.4)
        y = -h / 2 + 0.45
        return x, y, 0.3, 0.65

    # --- Modules radio/MCU : deux rangées le long des grands côtés
    if any(k in fp for k in _MODULE_KEYS):
        pitch = 1.27 if h < 18 else 2.54
        per_col = max(2, int((h - 1.6) // pitch) + 1)
        col, row = index // per_col, index % per_col
        x = (-w / 2 + 0.9) if col % 2 == 0 else (w / 2 - 0.9)
        y = clamp(-h / 2 + 1.4 + pitch * row + 0.9 * (col // 2),
                  -h / 2 + 0.6, h / 2 - 0.6)
        return x, y, 0.55, 0.9

    # --- IC (QFP/LQFP/QFN/LGA/SOIC/TSSOP...) : deux colonnes latérales
    if any(k in fp for k in _IC_KEYS):
        pitch = 1.27 if h < 8 else 2.0
        per_col = max(2, int((h - 1.8) // pitch) + 1)
        col, row = index // per_col, index % per_col
        x = -(w / 2 - 0.5) if col % 2 == 0 else (w / 2 - 0.5)
        y = clamp(-h / 2 + 0.9 + pitch * row + 0.635 * (col // 2),
                  -h / 2 + 0.4, h / 2 - 0.4)
        return x, y, 0.45, 0.3

    # --- Boîtiers linéaires & connecteurs : rangée (2e rangée si débordement)
    pitch = 2.54 if any(k in fp for k in ("header", "terminal", "kf301", "to-220",
                                          "to220", "jst", "ph2")) else 1.27
    usable = max(1.2, w - 1.2)
    pitch_eff = min(pitch, usable / max(1, index)) if index > 0 else pitch
    x = -w / 2 + 0.6 + pitch_eff * index
    y = -h / 2 + 0.5
    extra_rows = 0
    while x > w / 2 - 0.4:               # débordement → rangées suivantes
        extra_rows += 1
        x -= usable
        y += 1.25 * extra_rows
    return clamp(x, -w / 2 + 0.3, w / 2 - 0.3), clamp(y, -h / 2 + 0.3, h / 2 - 0.3), 0.6, 0.6
