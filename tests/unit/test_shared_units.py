"""Tests unitaires — unités physiques partagées (shared.units).

Conversions sûres mm ↔ mil/inch/cm/µm, Dimension avec unité explicite.
"""
from __future__ import annotations

import dataclasses

import pytest
from shared.units import Dimension, LengthUnit, copper_thickness_um, from_mm, mil, to_mm


class TestConversions:
    def test_mil_vers_mm(self) -> None:
        assert to_mm(10.0, LengthUnit.MIL) == pytest.approx(0.254)

    def test_raccourci_mil_jlcpcb(self) -> None:
        # 5 mil = 0.127 mm (cap process JLCPCB)
        assert mil(5.0) == pytest.approx(0.127)

    def test_inch_vers_mm(self) -> None:
        assert to_mm(1.0, LengthUnit.INCH) == pytest.approx(25.4)

    def test_cm_et_um(self) -> None:
        assert to_mm(1.0, LengthUnit.CM) == pytest.approx(10.0)
        assert to_mm(500.0, LengthUnit.UM) == pytest.approx(0.5)

    def test_from_mm(self) -> None:
        assert from_mm(25.4, LengthUnit.INCH) == pytest.approx(1.0)
        assert from_mm(0.127, LengthUnit.MIL) == pytest.approx(5.0)

    @pytest.mark.parametrize("unit", ["mm", "cm", "um", "mil", "inch"])
    def test_aller_retour_round_trip(self, unit: str) -> None:
        valeur = 3.7
        assert from_mm(to_mm(valeur, unit), unit) == pytest.approx(valeur)

    def test_unite_inconnue_leve_erreur(self) -> None:
        with pytest.raises(ValueError):
            to_mm(1.0, "parsec")

    def test_cuivre(self) -> None:
        assert copper_thickness_um(1.0) == pytest.approx(35.0)
        assert copper_thickness_um(2.0) == pytest.approx(70.0)


class TestDimension:
    def test_stockage_en_mm(self) -> None:
        d = Dimension.of(2.0, LengthUnit.CM)
        assert d.mm == pytest.approx(20.0)

    def test_lire_en_mil(self) -> None:
        d = Dimension.of(0.127, LengthUnit.MM)
        assert d.mil == pytest.approx(5.0)

    def test_addition_soustraction(self) -> None:
        a = Dimension.of(1.0, LengthUnit.MM)
        b = Dimension.of(0.254, LengthUnit.MM)
        assert (a + b).mm == pytest.approx(1.254)
        assert (a - b).mm == pytest.approx(0.746)

    def test_immuable(self) -> None:
        d = Dimension.of(1.0, LengthUnit.MM)
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.value_mm = 99.0  # type: ignore[misc]  # frozen dataclass
