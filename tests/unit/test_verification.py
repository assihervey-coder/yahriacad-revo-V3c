"""Tests unitaires — moteurs de vérification (ERC, DRC, DFM, QualityScorer).

ERC : pin flottant. DRC : clearance cuivre/cuivre + marge au bord.
DFM : dépassement du nombre de couches. QualityScorer : bornes 0..100.
"""
from __future__ import annotations

import pytest
from shared.geometry import Point, RoutePath

from services.design_core import DesignGraph
from services.design_core.design_graph.layers import Layer
from services.verification.dfm_engine import DFMEngine
from services.verification.drc_engine import DRCEngine
from services.verification.erc_engine import ERCEngine
from services.verification.quality_scoring import QualityScorer


class TestERC:
    def test_pin_flottant_detecte(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("U1", footprint="LQFP-48", x=20, y=20, placed=True)
        g.add_net(name="GND")
        g.connect("U1", "1", "N1")
        # le pad "2" existe-t-il ? on en crée un flottant explicitement
        from services.design_core import Pad
        g.get("U1").pads.append(Pad(name="2"))    # sans net → flottant

        report = ERCEngine().run(g)
        codes = {v.code for v in report.violations}
        assert "ERC_FLOATING_PIN" in codes
        assert any(v.severity == "warning" for v in report.violations
                   if v.code == "ERC_FLOATING_PIN")

    def test_net_unique_pin(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("R1")
        g.connect("R1", "1", "N1")                # net à 1 seul pin
        report = ERCEngine().run(g)
        assert any(v.code == "ERC_SINGLE_PIN" for v in report.violations)

    def test_design_connecte_passe(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("R1", footprint="0603")
        g.add_component("C1", footprint="0603")
        g.add_net(name="SIG")
        g.connect("R1", "1", "N1")
        g.connect("R1", "2", "N1")
        g.connect("C1", "1", "N1")
        g.connect("C1", "2", "N1")
        report = ERCEngine().run(g)
        assert report.passed is True
        assert report.score == pytest.approx(1.0)


class TestDRC:
    def test_clearance_entre_deux_nets(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=5, y=5, placed=True)
        g.add_component("R2", footprint="0603", x=5, y=25, placed=True)
        g.add_net(name="A")
        g.add_net(name="B")
        g.nets["N1"].path = RoutePath(net_id="N1", points=[Point(0, 5), Point(40, 5)],
                                      layer=0, width_mm=0.25)
        g.nets["N2"].path = RoutePath(net_id="N2", points=[Point(0, 5.1), Point(40, 5.1)],
                                      layer=0, width_mm=0.25)
        g.nets["N1"].routed = True
        g.nets["N2"].routed = True

        report = DRCEngine().run(g)
        codes = {v.code for v in report.violations}
        assert "DRC_CLEARANCE" in codes           # 0.1 mm < 0.2 mm

    def test_marge_bord_violee(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=0.2, y=20, placed=True)
        report = DRCEngine().run(g)
        assert any(v.code == "DRC_EDGE_MARGIN" for v in report.violations)

    def test_design_distant_passe(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50, 40))
        g.add_component("R1", footprint="0603", x=5, y=5, placed=True)
        g.add_component("R2", footprint="0603", x=5, y=30, placed=True)
        report = DRCEngine().run(g)
        erreurs = [v for v in report.violations if v.severity == "error"]
        assert erreurs == []


class TestDFM:
    def test_trop_de_couches(self) -> None:
        g = DesignGraph(project_id="t")
        g.layers = [Layer(i, f"L{i}") for i in range(25)]   # > max_layers JLCPCB (20)
        report = DFMEngine(factory="jlcpcb").run(g)
        assert any(v.code == "DFM_MAX_LAYERS" for v in report.violations)
        assert report.factory == "jlcpcb"

    def test_4_couches_jlcpcb_passe(self) -> None:
        g = DesignGraph(project_id="t")           # stackup 4 couches par défaut
        report = DFMEngine(factory="jlcpcb").run(g)
        assert report.passed is True

    def test_usine_inconnue_repli_jlcpcb(self) -> None:
        g = DesignGraph(project_id="t")
        report = DFMEngine(factory="usine-fantome").run(g)
        # le nom demandé est conservé dans le rapport, mais le PROFIL utilisé
        # est bien celui de JLCPCB (repli documenté de ManufacturingRules)
        from services.verification.manufacturing_rules import ManufacturingRules
        assert ManufacturingRules.get("usine-fantome")["name"] == "JLCPCB"
        assert report.passed is True              # 4 couches acceptées partout


class TestQualityScorer:
    def test_bornes_0_100(self, design_graph) -> None:
        qs = QualityScorer().score(design_graph, reports={})
        assert 0.0 <= qs.total <= 100.0
        assert set(qs.breakdown) == {"erc", "drc", "dfm", "routing_completeness",
                                     "thermal", "signal_integrity", "cost_efficiency"}

    def test_pire_et_meilleur_score(self, design_graph) -> None:
        # design « bon » : net routé + simulations fictives parfaites
        g_bon = design_graph.copy()
        g_bon.nets["N1"].routed = True
        sim_results = {
            "thermal": {"metrics": {"max_temp_c": 30.0}},
            "signal_integrity": {"passed": True},
        }
        scorer = QualityScorer()
        pire = scorer.score(design_graph, reports={
            "erc": {"score": 0.0, "passed": False},
            "drc": {"score": 0.0, "passed": False},
            "dfm": {"score": 0.0, "passed": False},
        })
        bon = scorer.score(g_bon, reports={
            "erc": {"score": 1.0, "passed": True},
            "drc": {"score": 1.0, "passed": True},
            "dfm": {"score": 1.0, "passed": True},
            "sim_results": sim_results,
        })
        assert pire.total < bon.total
        assert bon.total > 80.0
        assert 0.0 <= pire.total <= 100.0

    def test_notes_sur_nets_non_routes(self, design_graph) -> None:
        qs = QualityScorer().score(design_graph)
        assert any("non routé" in note for note in qs.notes)
