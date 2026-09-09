"""Couches cuivre et stackup par défaut du design graph."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Layer:
    """Couche du circuit imprimé (cuivre) avec type et paramètres diélectriques."""

    index: int
    name: str
    ltype: str = "signal"        # signal | ground | power | mixed
    thickness_um: float = 35.0   # épaisseur cuivre
    er: float = 4.3              # permittivité relative (FR4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "ltype": self.ltype,
            "thickness_um": self.thickness_um,
            "er": self.er,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Layer:
        return cls(
            index=int(d.get("index", 0) or 0),
            name=str(d.get("name", f"L{d.get('index', 0)}")),
            ltype=str(d.get("ltype", d.get("type", "signal")) or "signal"),
            thickness_um=float(d.get("thickness_um", 35.0) or 35.0),
            er=float(d.get("er", 4.3) or 4.3),
        )


def make_default_stackup(n_layers: int = 4) -> list[Layer]:
    """Stackup standard : 2 couches (F.Cu/B.Cu), 4 (F.Cu/GND/PWR/B.Cu), 6 ou générique."""
    if n_layers <= 2:
        return [Layer(0, "F.Cu"), Layer(1, "B.Cu")]
    if n_layers == 4:
        return [
            Layer(0, "F.Cu", "signal"),
            Layer(1, "GND", "ground"),
            Layer(2, "PWR", "power"),
            Layer(3, "B.Cu", "signal"),
        ]
    if n_layers == 6:
        return [
            Layer(0, "F.Cu", "signal"),
            Layer(1, "GND", "ground"),
            Layer(2, "SIG2", "signal"),
            Layer(3, "PWR", "power"),
            Layer(4, "GND", "ground"),
            Layer(5, "B.Cu", "signal"),
        ]
    # Générique : cuivres externes + plans de masse/alternés à l'intérieur.
    layers: list[Layer] = [Layer(0, "F.Cu", "signal")]
    for i in range(1, n_layers - 1):
        layers.append(Layer(i, "GND" if i % 2 == 1 else f"SIG{i}", "ground" if i % 2 == 1 else "signal"))
    layers.append(Layer(n_layers - 1, "B.Cu", "signal"))
    return layers
