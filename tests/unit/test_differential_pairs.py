"""Tests des paires différentielles enrichies (couplage, skew, rapport)."""
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "backend")]

import math

import pytest

from services.design_core import DesignGraph
from services.router.differential_pairs import (
    DifferentialPairRouter,
    PairQualityReport,
    find_differential_pairs,
)
from services.router.geometrical import MazeRouter


@pytest.fixture
def usb_graph():
    g = DesignGraph(project_id="t", name="t", board_size=(60.0, 40.0))
    g.add_component(ref="U1", footprint="QFN-16_0.5mm", x=10, y=20)
    g.add_component(ref="J1", footprint="USB-C_0.5mm", x=50, y=20)
    g.connect("U1", "A5", "USB_DP")
    g.connect("J1", "A5", "USB_DP")
    g.connect("U1", "A6", "USB_DM")
    g.connect("J1", "A6", "USB_DM")
    return g


def test_detection_par_suffixe_sans_classe(usb_graph):
    pairs = find_differential_pairs(usb_graph)
    assert len(pairs) == 1
    p, n = pairs[0]
    assert {p.name, n.name} == {"USB_DP", "USB_DM"}


def test_detection_par_matched_group(usb_graph):
    usb_graph.nets["USB_DP"].matched_group = "usb"
    usb_graph.nets["USB_DM"].matched_group = "usb"
    pairs = find_differential_pairs(usb_graph)
    assert len(pairs) == 1


def test_routage_paire_rapport_qualite(usb_graph):
    pairs = find_differential_pairs(usb_graph)
    router = DifferentialPairRouter(maze=MazeRouter(board_size=usb_graph.board_size))
    rep = router.route_pair(usb_graph, pairs[0][0], pairs[0][1], 0.2)
    assert isinstance(rep, PairQualityReport)
    d = rep.to_dict()
    assert d["skew_matched"] is True or d["skew_mm"] <= 0.15 + 1e-6
    assert d["coupling_ratio"] > 0.2
    assert d["length_p_mm"] > 10.0 and d["length_n_mm"] > 10.0
    assert d["strategy"] in ("offset", "astar_fallback")
    assert math.isfinite(d["min_gap_mm"] or math.inf) or d["min_gap_mm"] is None


def test_route_all_pairs(usb_graph):
    router = DifferentialPairRouter(maze=MazeRouter(board_size=usb_graph.board_size))
    reports = router.route_all_pairs(usb_graph)
    assert len(reports) == 1
    assert usb_graph.nets["USB_DP"].routed
    assert usb_graph.nets["USB_DM"].routed


def test_well_coupled_propriete():
    rep = PairQualityReport(name="t", net_p="A", net_n="B",
                            coupling_ratio=0.8, min_gap_mm=0.3)
    assert rep.well_coupled is True
    rep2 = PairQualityReport(name="t", net_p="A", net_n="B",
                             coupling_ratio=0.1, min_gap_mm=0.3)
    assert rep2.well_coupled is False
