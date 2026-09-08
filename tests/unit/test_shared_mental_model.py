"""Tests unitaires — SharedMentalModel (mémoire de contexte des agents).

record_decision / record_tradeoff / confidence par domaine / export_for_llm /
snapshot-restore.
"""
from __future__ import annotations

import pytest

from services.design_core import SharedMentalModel
from services.design_core.shared_mental_model import ConfidenceTracker


class TestDecisions:
    def test_record_decision_et_filtrage(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.record_decision("placement", "U1 proche du bord esthétique", "minimise IR drop", 0.8,
                            domain="placement")
        smm.record_decision("router", "route GND en premier", "plan de masse", 0.9,
                            domain="routing")

        assert len(smm.decisions()) == 2
        assert len(smm.decisions_by(domain="routing")) == 1
        assert smm.decisions_by(actor="placement")[0].decision.startswith("U1")

    def test_confiance_mise_a_jour_par_domaine(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.record_decision("placement", "d1", "r1", 0.7, domain="placement")
        assert smm.confidence.get("placement") == 0.7


class TestTradeoffsEtContexte:
    def test_record_tradeoff_clampe(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        t = smm.record_tradeoff("coût", "fiabilité", "a", weight=1.7)
        assert t.weight == 1.0                    # clampé 0..1
        assert len(smm.tradeoffs()) == 1

    def test_update_context_fusion(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.update_context("simulation", {"thermal_ok": True})
        smm.update_context("simulation", {"si_ok": False})
        ctx = smm.context("simulation")
        assert ctx == {"thermal_ok": True, "si_ok": False}

    def test_sync_from_graph_alimente_le_domaine_design(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        ctx = smm.context("design")
        assert ctx["stats"]["components"] == 2
        assert "N1" in ctx["unrouted_nets"]       # net déclaré mais non routé


class TestExportLLM:
    def test_export_for_llm_contient_les_sections(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.record_decision("placement", "choix A", "car B trop coûteux", 0.75)
        smm.record_tradeoff("longueur pistes", "coût vias", "compromis", 0.4)
        texte = smm.export_for_llm()

        assert "CONTEXTE PROJET" in texte
        assert "[État du design]" in texte
        assert "[Dernières décisions]" in texte
        assert "[Arbitrages]" in texte
        assert "placement" in texte               # acteur présent

    def test_confiance_globale_dans_le_export(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.record_decision("placement", "d", "r", 0.9)
        assert "[Confiance]" in smm.export_for_llm()


class TestSnapshot:
    def test_snapshot_restore_round_trip(self, design_graph) -> None:
        smm = SharedMentalModel(graph=design_graph)
        smm.record_decision("validator", "verdict", "3 erreurs DRC", 0.6)
        smm.record_tradeoff("surface", "coût", "surface", 0.9)
        smm.update_context("human", {"canceled": False})

        clone = SharedMentalModel.restore(smm.snapshot())
        assert [d.decision for d in clone.decisions()] == ["verdict"]
        assert clone.context("human") == {"canceled": False}
        assert len(clone.tradeoffs()) == 1


class TestConfidenceTracker:
    def test_defaut_0_5_et_ponderation(self) -> None:
        tracker = ConfidenceTracker()
        assert tracker.get("physical") == 0.5
        assert tracker.global_score() == 0.5      # vide → défaut
        tracker.update("physical", 1.0)           # poids 1.5
        assert tracker.global_score() == 1.0
        tracker.update("general", 0.0)            # poids 1.0
        expected = (1.0 * 1.5 + 0.0 * 1.0) / 2.5
        assert tracker.global_score() == pytest.approx(expected)

    def test_report_inclut_global(self) -> None:
        tracker = ConfidenceTracker()
        tracker.update("design", 0.8)
        assert tracker.report()["global"] == 0.8
