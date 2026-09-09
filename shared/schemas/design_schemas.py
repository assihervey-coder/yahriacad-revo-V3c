"""Schémas du design PCB — sérialisables (pydantic), utilisés par l'API,
le design_core et l'exporter. La source de vérité reste le DesignGraph ;
ces schémas en sont la représentation filaire.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class LayerType(StrEnum):
    SIGNAL = "signal"
    POWER = "power"
    GROUND = "ground"
    MIXED = "mixed"


class LayerSchema(BaseModel):
    index: int
    name: str = "F.Cu"
    type: LayerType = LayerType.SIGNAL
    thickness_um: float = 35.0
    dielectric_thickness_um: float = 210.0
    er: float = 4.3  # permittivité relative FR4


class PadSchema(BaseModel):
    name: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    width_mm: float = 0.6
    height_mm: float = 0.6
    net_id: str | None = None
    layer: int = 0


class ComponentSchema(BaseModel):
    ref: str                       # "R1", "U3", "C12"
    value: str = ""
    footprint: str = ""            # "0402", "SOIC-8", "QFN-32"...
    mpn: str = ""                  # référence fabricant
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation_deg: float = 0.0
    side: str = "top"              # top | bottom
    bbox_mm: tuple[float, float] = (1.0, 0.5)
    pads: list[PadSchema] = Field(default_factory=list)
    power_w: float = 0.0           # dissipation thermique estimée
    price_usd: float = 0.0


class NetSchema(BaseModel):
    net_id: str
    name: str = ""
    class_name: str = "default"    # default | power | high_speed | differential | analog
    pins: list[tuple[str, str]] = Field(default_factory=list)  # (ref, pad)
    impedance_target_ohm: float | None = None
    max_length_mm: float | None = None
    matched_group: str | None = None   # groupe de longueur appariée
    routed: bool = False


class DesignSchema(BaseModel):
    """Représentation filaire complète d'un design (snapshot/branch/API)."""

    project_id: str
    name: str = "untitled"
    revision: int = 0
    board_size_mm: tuple[float, float] = (100.0, 80.0)
    layers: list[LayerSchema] = Field(default_factory=lambda: [
        LayerSchema(index=0, name="F.Cu"),
        LayerSchema(index=1, name="GND", type=LayerType.GROUND),
        LayerSchema(index=2, name="PWR", type=LayerType.POWER),
        LayerSchema(index=3, name="B.Cu"),
    ])
    components: list[ComponentSchema] = Field(default_factory=list)
    nets: list[NetSchema] = Field(default_factory=list)
    keepouts: list[dict] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "components": len(self.components),
            "nets": len(self.nets),
            "layers": len(self.layers),
        }
