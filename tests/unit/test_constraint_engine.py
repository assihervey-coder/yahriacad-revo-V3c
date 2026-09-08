"""Tests unitaires — ConstraintEngine (11 contraintes standard, score 0..1).

register_defaults + evaluate → violations attendues sur des graphes précis.
"""
from __future__ import annotations

import pytest

from services.design_core import ConstraintEngine, DesignGraph
from services.design_core.constraint_engine import MinTraceWidth
from services.design_core.constraint_engine.cost import MaxCostUSD
from services.design_core.constraint_engine.mechanical import MinClearance
from services.design_core.constraint_engine.thermal import ThermalHotspot


def _moteur() -> ConstraintEngine:
    return ConstraintEngine().register_defaults()


class TestRegistre:
    def test_register_defaults_11_contraintes(self) -> None:
        assert len(_moteur().constraints) == 11

    def test_categories_couvertes(self) -> None:
        categories = {c.category for c in _moteur().constraints}
        assert {"mechanical", "electrical", "manufacturing", "thermal", "cost"} <= categories


class TestGraphPropre:
    def test_design_valide_pas_de_violation(self, design_graph: DesignGraph) -> None:
        report = _moteur().evaluate(design_graph)
        assert report.passed is True
        assert report.violations == []
        assert report.score == pytest.approx(1.0)


class TestViolationsAttendues:
    def test_min_clearance_composants_trop_proches(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=10.0, y=10.0, placed=True)
        g.add_component("R2", footprint="0603", x=10.5, y=10.0, placed=True)
        report = _moteur().evaluate(g)
        ids = {v.constraint_id for v in report.violations}
        assert "min_clearance" in ids
        assert report.passed is False            # sévérité error

    def test_board_outline_composant_hors_carte(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=0.0, y=20.0, placed=True)
        report = _moteur().evaluate(g)
        assert any(v.constraint_id == "board_outline" for v in report.violations)

    def test_keepout_empietement(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.keepout_add("antenne", [[18, 18], [22, 18], [22, 22], [18, 22]])
        g.add_component("R1", footprint="0603", x=20.0, y=20.0, placed=True)
        report = _moteur().evaluate(g)
        assert any(v.constraint_id == "keepout_violation" for v in report.violations)

    def test_thermal_hotspot_densite_excessive(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("U1", footprint="LQFP-48", x=10.0, y=10.0,
                        power_w=2.0, placed=True)
        report = _moteur().evaluate(g)
        assert any(v.constraint_id == "thermal_hotspot" for v in report.violations)

    def test_max_cost_usd_depassement(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("U1", price_usd=120.0)
        moteur = ConstraintEngine().register(MaxCostUSD(max_usd=50.0))
        report = moteur.evaluate(g)
        assert len(report.violations) == 1
        assert report.violations[0].constraint_id == "max_cost_usd"
        assert report.passed is False

    def test_min_trace_width_classe_power(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_net(name="PWR", class_name="power")     # proxy 0.5 mm (OK à 0.2)
        moteur = ConstraintEngine().register(MinTraceWidth(min_width_mm=1.0))
        report = moteur.evaluate(g)
        assert report.violations[0].constraint_id == "min_trace_width"
        assert report.violations[0].severity == "warning"


class TestScore:
    def test_score_borne_0_1(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=10.0, y=10.0, placed=True)
        g.add_component("R2", footprint="0603", x=10.1, y=10.0, placed=True)
        g.add_component("R3", footprint="0603", x=10.2, y=10.0, placed=True)
        report = _moteur().evaluate(g)
        assert 0.0 <= report.score <= 1.0
        assert report.checked == 11
        assert report.by_severity().get("error", 0) >= 1

    def test_to_dict_shape(self, design_graph: DesignGraph) -> None:
        payload = _moteur().evaluate(design_graph).to_dict()
        assert {"checked", "passed", "score", "by_severity", "violations"} <= set(payload)
