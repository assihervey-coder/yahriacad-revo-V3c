"""Unités physiques — conversions sûres pour toute la plateforme.

Le format interne est le **millimètre** et le **volt**. Tout module qui
manipule des dimensions doit passer par ces helpers (aucun float nu sans unité).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LengthUnit(StrEnum):
    MM = "mm"
    CM = "cm"
    UM = "um"
    MIL = "mil"
    INCH = "inch"


class MassUnit(StrEnum):
    G = "g"
    KG = "kg"
    OZ = "oz"  # oz/ft² pour le cuivre


MM_PER = {
    LengthUnit.MM: 1.0,
    LengthUnit.CM: 10.0,
    LengthUnit.UM: 1e-3,
    LengthUnit.MIL: 0.0254,
    LengthUnit.INCH: 25.4,
}

# épaisseur cuivre standard (oz/ft² -> µm)
COPPER_WEIGHT_UM = {0.5: 17.5, 1.0: 35.0, 2.0: 70.0, 3.0: 105.0}


def to_mm(value: float, unit: LengthUnit | str) -> float:
    """Convertit une longueur vers le millimètre (format interne)."""
    unit = LengthUnit(unit)
    return value * MM_PER[unit]


def from_mm(value_mm: float, unit: LengthUnit | str) -> float:
    """Convertit depuis le millimètre vers l'unité demandée."""
    unit = LengthUnit(unit)
    return value_mm / MM_PER[unit]


def mil(value: float) -> float:
    """Raccourci : mil -> mm."""
    return to_mm(value, LengthUnit.MIL)


def copper_thickness_um(weight_oz: float) -> float:
    """Épaisseur de cuivre en µm pour un poids en oz/ft² (1 oz ≈ 35 µm)."""
    return weight_oz * 35.0


@dataclass(frozen=True)
class Dimension:
    """Dimension avec unité explicite, toujours stockée en mm."""

    value_mm: float

    @classmethod
    def of(cls, value: float, unit: LengthUnit | str = LengthUnit.MM) -> Dimension:
        return cls(to_mm(value, unit))

    @property
    def mm(self) -> float:
        return self.value_mm

    @property
    def mil(self) -> float:
        return from_mm(self.value_mm, LengthUnit.MIL)

    def __add__(self, other: Dimension) -> Dimension:
        return Dimension(self.value_mm + other.value_mm)

    def __sub__(self, other: Dimension) -> Dimension:
        return Dimension(self.value_mm - other.value_mm)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Dimension({self.value_mm:.4f}mm)"
