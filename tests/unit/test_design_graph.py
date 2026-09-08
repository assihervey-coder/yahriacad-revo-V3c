"""Tests unitaires — DesignGraph (design_core, source de vérité unique).

add_component / add_net (IDs auto) / connect / place / stats / copy profonde /
to_dict→from_dict round-trip strict / keepouts.
"""
from __future__ import annotations

import pytest

from services.design_core import DesignGraph


class TestComposantsEtNets:
    def test_add_component_bbox_depuis_empreinte(self, design_graph: DesignGraph) -> None:
        comp = design_graph.get("R1")
        assert comp.bbox == (1.6, 0.8)           # empreinte 0603
        assert comp.placed is True

    def test_add_net_ids_auto(self) -> None:
        g = DesignGraph(project_id="t")
        n1 = g.add_net(name="GND")
        n2 = g.add_net(name="VCC")
        assert (n1.net_id, n2.net_id) == ("N1", "N2")

    def test_connect_cree_pad_implicite_et_net(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("U1")
        net = g.connect("U1", "VDD", "PWR")       # net créé à la volée + pad implicite
        assert net.net_id == "PWR"
        assert g.net_of("U1", "VDD") is net
        assert ("U1", "VDD") in net.pins

    def test_net_of_sans_connection(self, design_graph: DesignGraph) -> None:
        design_graph.add_component("X1")
        assert design_graph.net_of("X1", "1") is None

    def test_place_marque_placed(self) -> None:
        g = DesignGraph(project_id="t")
        g.add_component("R1", footprint="0603")
        assert g.placed_components() == []
        g.place("R1", 5.0, 6.0, rotation=90.0)
        comp = g.placed_components()[0]
        assert (comp.x, comp.y, comp.rotation) == (5.0, 6.0, 90.0)

    def test_get_inconnu_leve_keyerror(self, design_graph: DesignGraph) -> None:
        with pytest.raises(KeyError):
            design_graph.get("Z99")
        with pytest.raises(KeyError):
            design_graph.get_net("N999")


class TestStatsEtMetriques:
    def test_stats_clefs(self, design_graph: DesignGraph) -> None:
        stats = design_graph.stats()
        assert stats["components"] == 2
        assert stats["placed"] == 2
        assert stats["nets"] == 1
        assert stats["layers"] == 4               # stackup par défaut
        assert {"routed", "wire_length_mm", "cost_usd"} <= set(stats)

    def test_utilization_et_cout(self) -> None:
        g = DesignGraph(project_id="t", board_size=(100.0, 100.0))
        g.add_component("R1", footprint="0603", x=50, y=50, price_usd=0.01, placed=True)
        assert 0.0 < g.utilization() < 0.01
        assert g.cost_usd() == pytest.approx(0.01)


class TestCopyEtSerialisation:
    def test_copy_est_profonde(self, design_graph: DesignGraph) -> None:
        clone = design_graph.copy()
        clone.place("R1", 99.0, 99.0)
        clone.add_component("Z1")
        assert design_graph.get("R1").x == 10.0   # l'original est intact
        assert "Z1" not in design_graph.components

    def test_to_dict_from_dict_round_trip(self, design_graph: DesignGraph) -> None:
        snapshot = design_graph.to_dict()
        restored = DesignGraph.from_dict(snapshot)
        assert restored.project_id == design_graph.project_id
        assert restored.board_size == design_graph.board_size
        assert restored.stats() == design_graph.stats()
        assert set(restored.components) == set(design_graph.components)
        assert set(restored.nets) == set(design_graph.nets)
        # second passage : stabilité
        assert DesignGraph.from_dict(restored.to_dict()).stats() == restored.stats()


class TestKeepouts:
    def test_keepout_violation(self) -> None:
        g = DesignGraph(project_id="t", board_size=(50.0, 40.0))
        g.keepout_add("zone_antenne", [[18, 18], [22, 18], [22, 22], [18, 22]])
        assert g.violates_keepouts(20.0, 20.0, 4.0, 4.0), \
            "bbox centrée dans le keepout doit violer"
        assert not g.violates_keepouts(5.0, 5.0, 4.0, 4.0)

    def test_keepout_contour_seulement(self) -> None:
        g = DesignGraph(project_id="t")
        g.keepout_add("coin", [[0, 0], [1, 0], [1, 1], [0, 1]])
        # coin de bbox effleurant le polygone
        assert not g.violates_keepouts(-2.0, -2.0, 2.0, 2.0)
