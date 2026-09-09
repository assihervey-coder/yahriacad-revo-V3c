"""Nets — connexions électriques entre pads, avec contraintes de routage."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.geometry import Point, RoutePath


def routepath_to_dict(path: RoutePath) -> dict[str, Any]:
    """Sérialise un RoutePath en dict JSON-compatible."""
    return {
        "net_id": path.net_id,
        "points": [[p.x, p.y] for p in path.points],
        "layer": path.layer,
        "width_mm": path.width_mm,
        "vias": [[[v[0].x, v[0].y], v[1], v[2]] for v in path.vias],
    }


def routepath_from_dict(d: dict[str, Any]) -> RoutePath:
    """Reconstruit un RoutePath depuis sa sérialisation."""
    return RoutePath(
        net_id=str(d.get("net_id", "")),
        points=[Point.from_tuple(p) for p in d.get("points", [])],
        layer=int(d.get("layer", 0) or 0),
        width_mm=float(d.get("width_mm", 0.2) or 0.2),
        vias=[(Point.from_tuple(v[0]), int(v[1]), int(v[2])) for v in d.get("vias", [])],
    )


@dataclass
class Net:
    """Net électrique : liste de pins (ref, pad) + contraintes SI/SI+ de classe."""

    net_id: str
    name: str = ""
    class_name: str = "default"   # default | power | high_speed | differential | analog
    pins: list[tuple[str, str]] = field(default_factory=list)   # (ref, pad)
    impedance_target_ohm: float | None = None
    max_length_mm: float | None = None
    matched_group: str | None = None
    routed: bool = False
    path: RoutePath | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_id": self.net_id,
            "name": self.name,
            "class_name": self.class_name,
            "pins": [[ref, pad] for ref, pad in self.pins],
            "impedance_target_ohm": self.impedance_target_ohm,
            "max_length_mm": self.max_length_mm,
            "matched_group": self.matched_group,
            "routed": self.routed,
            "path": routepath_to_dict(self.path) if self.path is not None else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Net:
        pins_raw = d.get("pins", [])
        pins: list[tuple[str, str]] = []
        for p in pins_raw:
            if isinstance(p, dict):          # {"ref": "R1", "pin": "1"}
                pins.append((str(p.get("ref", "")), str(p.get("pin", p.get("pad", "")))))
            else:                            # ["R1", "1"]
                pins.append((str(p[0]), str(p[1])))
        path_d = d.get("path")
        return cls(
            net_id=str(d.get("net_id", d.get("code", ""))),
            name=str(d.get("name", "") or ""),
            class_name=str(d.get("class_name", "default") or "default"),
            pins=pins,
            impedance_target_ohm=(
                float(d["impedance_target_ohm"]) if d.get("impedance_target_ohm") is not None else None
            ),
            max_length_mm=float(d["max_length_mm"]) if d.get("max_length_mm") is not None else None,
            matched_group=d.get("matched_group"),
            routed=bool(d.get("routed", False)),
            path=routepath_from_dict(path_d) if path_d else None,
        )
