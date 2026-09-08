"""Tests unitaires — parseurs d'entrée (services.parser).

Netlist KiCad s-expression, NL→SKIDL (template déterministe), extraction de
contraintes en langage naturel.
"""
from __future__ import annotations

import pytest

from services.design_core import DesignGraph
from services.design_core.constraint_engine import ImpedanceTarget
from services.design_core.constraint_engine.cost import MaxCostUSD
from services.design_core.constraint_engine.electrical import MinTraceWidth
from services.parser import NLToSkidl, extract, parse_netlist

SEXP_NETLIST = """(export
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "C1") (value "100n") (footprint "Capacitor_SMD:C_0402_1005Metric")))
  (nets
    (net (code "1") (name "GND")
      (node (ref "R1") (pin "1"))
      (node (ref "C1") (pin "1")))
    (net (code "2") (name "SIG")
      (node (ref "R1") (pin "2"))
      (node (ref "C1") (pin "2")))))
"""

JSON_NETLIST = """{
  "project_id": "json-import",
  "components": [
    {"ref": "R1", "value": "10k", "footprint": "0603"},
    {"ref": "C1", "value": "100n", "footprint": "0402"}
  ],
  "nets": [
    {"name": "GND", "pins": [["R1", "1"], ["C1", "1"]]}
  ]
}"""


class TestNetlistSExpr:
    def test_composants_et_nets(self) -> None:
        g = parse_netlist(SEXP_NETLIST)
        assert isinstance(g, DesignGraph)
        assert set(g.components) == {"R1", "C1"}
        assert len(g.nets) == 2
        assert g.get("R1").bbox == (1.6, 0.8)     # bbox déduite de l'empreinte 0603

    def test_connections(self) -> None:
        g = parse_netlist(SEXP_NETLIST)
        gnd = next(n for n in g.nets.values() if n.name == "GND")
        assert ("R1", "1") in gnd.pins
        assert g.net_of("C1", "1") is gnd

    def test_composants_implicites_format_json(self) -> None:
        # netlist JSON minimale sans section composants complète → composants
        # implicites créés depuis les pins des nets (repli déterministe)
        mini = '{"nets": [{"name": "A", "pins": [["X1", "1"], ["X2", "1"]]}]}'
        g = parse_netlist(mini)
        assert {"X1", "X2"} <= set(g.components)
        assert g.net_of("X1", "1") is not None


class TestNetlistJSON:
    def test_import_json(self) -> None:
        g = parse_netlist(JSON_NETLIST)
        assert g.project_id == "json-import"
        assert set(g.components) == {"R1", "C1"}
        gnd = next(n for n in g.nets.values() if n.name == "GND")
        assert gnd.pins == [("R1", "1"), ("C1", "1")]

    def test_netlist_vide_leve_erreur(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            parse_netlist("   ")


class TestNLToSkidl:
    def test_template_deterministe_esp32(self) -> None:
        script = NLToSkidl().translate(
            "une carte ESP32 avec capteur BME680, un régulateur 3.3V et un connecteur USB-C")
        assert len(script.components) >= 3         # BOM réaliste du template
        assert script.code.strip()                 # code SKIDL généré

    def test_build_graph_execute_le_script(self) -> None:
        script = NLToSkidl().translate("carte ESP32 minimal")
        g = NLToSkidl().build_graph(script)
        assert isinstance(g, DesignGraph)
        assert len(g.components) >= 2
        assert len(g.nets) >= 1
        assert any(n.class_name == "power" for n in g.nets.values())


class TestConstraintExtractor:
    def test_extraction_multiple(self) -> None:
        text = ("carte 4 couches avec impédance 50 ohm, min trace 0.2mm, "
                "budget max 30 USD, fabriqué chez JLCPCB, garde le plan de masse")
        contraintes = extract(text)
        par_id = {c.constraint_id for c in contraintes}
        assert "param.layer_count" in par_id
        assert "impedance_target" in par_id
        assert "min_trace_width" in par_id
        assert "max_cost_usd" in par_id
        assert "mfg.jlcpcb_capability" in par_id
        assert "param.ground_plane" in par_id

    def test_valeurs_extraites(self) -> None:
        contraintes = extract("impedance 50 ohm, budget max 30, fabrication JLCPCB")
        imp = next(c for c in contraintes if isinstance(c, ImpedanceTarget))
        assert imp.required_ohm == pytest.approx(50.0)
        budget = next(c for c in contraintes if isinstance(c, MaxCostUSD))
        assert budget.max_usd == pytest.approx(30.0)
        cap = next(c for c in contraintes if c.constraint_id == "mfg.jlcpcb_capability")
        assert isinstance(cap, MinTraceWidth)
        assert cap.min_width_mm == pytest.approx(0.127)

    def test_texte_sans_contrainte(self) -> None:
        assert extract("bonjour le monde") == []
