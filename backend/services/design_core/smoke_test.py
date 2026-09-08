"""Smoke test du design_core + parser — exécution : DESIGN CORE OK attendu.

Lancement :
  cd /home/z/my-project/pcb_ai_designer_v3 && \\
  PYTHONPATH=.:backend python3 -c "exec(open('backend/services/design_core/smoke_test.py').read())"
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from shared.utilities import configure_logging

from services.design_core import (
    ConstraintEngine,
    DesignGraph,
    DesignVersioning,
    IntentGraph,
    SharedMentalModel,
    get_constraint_bus,
)
from services.parser import (
    ComponentLibMatcher,
    NLToSkidl,
    extract,
    parse_netlist,
    parse_pcb,
    parse_schematic,
)

configure_logging("WARNING")


def main() -> None:
    # 1) DesignGraph : 3 composants, 2 nets, connect, place --------------------
    graph = DesignGraph(project_id="smoke", name="smoke-test")
    graph.add_component("U1", value="ESP32-WROOM-32E", footprint="ESP32-WROOM-32E",
                        mpn="ESP32-WROOM-32E-N8", power_w=0.5, price_usd=2.9)
    graph.add_component("R1", value="10k", footprint="0402", price_usd=0.004)
    graph.add_component("C1", value="100nF", footprint="0402", price_usd=0.004)
    graph.add_net(net_id="PWR", name="PWR", class_name="power")
    graph.add_net(net_id="GND", name="GND", class_name="power")
    graph.connect("U1", "VDD", "PWR")
    graph.connect("R1", "1", "PWR")
    graph.connect("U1", "GND", "GND")
    graph.connect("C1", "2", "GND")
    graph.place("U1", 30.0, 40.0)
    graph.place("R1", 20.0, 40.0)
    graph.place("C1", 40.0, 40.0)
    graph.keepout_add("antenna_zone", [(0, 0), (10, 0), (10, 10), (0, 10)])
    assert graph.net_of("U1", "VDD") is graph.get_net("PWR")
    assert len(graph.unrouted_nets()) == 2
    stats = graph.stats()
    assert stats["components"] == 3 and stats["placed"] == 3 and stats["nets"] == 2
    schema = graph.to_schema()                     # pont vers shared.schemas (pydantic)
    assert DesignGraph.from_schema(schema).stats() == stats
    print(f"[1] DesignGraph OK — stats={stats}, coût={graph.cost_usd():.3f}$")

    # 2) ConstraintEngine : defaults + evaluate --------------------------------
    engine = ConstraintEngine().register_defaults()
    report = engine.evaluate(graph)
    assert report.checked == 11
    assert 0.0 <= report.score <= 1.0
    print(f"[2] ConstraintEngine OK — checked={report.checked}, passed={report.passed}, "
          f"score={report.score:.3f}, violations={len(report.violations)}")

    # 3) Versioning : 2 commits, branches, restore, diff -----------------------
    versioning = DesignVersioning("smoke")
    versioning.commit(graph, "révision initiale", author="design_core")
    graph.place("R1", 21.0, 40.0)
    graph.add_component("D1", value="LED", footprint="0603", price_usd=0.03)
    revision2 = versioning.commit(graph, "R1 déplacé + LED", author="placement")
    graph_restored = versioning.restore(revision2.parent_rev)   # rollback r1
    assert "D1" not in graph_restored.components
    diff = versioning.diff(1, 2)
    assert diff["components_added"] == ["D1"] and diff["components_moved"].get("R1")
    with tempfile.TemporaryDirectory() as tmp:
        path = versioning.persist(str(Path(tmp) / "versions.json"))
        reloaded = DesignVersioning.load(str(path))
        assert reloaded.get(2).message == revision2.message
    print(f"[3] DesignVersioning OK — révisions={len(versioning.list())}, "
          f"diff(r1,r2)={diff['components_added']} moved={list(diff['components_moved'])}")

    # 4) SharedMentalModel : contexte, décisions, tradeoffs, export LLM --------
    intents = IntentGraph("smoke")
    intents.add_intent("Carte capteur environnemental USB-C", kind="functional", priority=1)
    intents.add_intent("Impédance 50 ohm sur USB", kind="constraint", priority=2, parent_id="I1")
    model = SharedMentalModel(graph=graph, intents=intents)
    model.record_decision("placement_agent", "R1 déplacé près de U1",
                          "réduit le HPWL de 12 %", 0.82, domain="placement")
    model.record_tradeoff("coût", "fiabilité", "a", weight=0.7)
    model.confidence.update("routing", 0.75)
    model.sync_from_graph()
    llm_context = model.export_for_llm()
    assert "Intentions" in llm_context and "Dernières décisions" in llm_context
    restored_model = SharedMentalModel.restore(model.snapshot())
    assert len(restored_model.decisions_by(actor="placement_agent")) == 1
    print(f"[4] SharedMentalModel OK — confiance={model.confidence.report()}")

    # 5) ConstraintBus : pub/sub + historique ----------------------------------
    bus = get_constraint_bus("smoke")
    received: list[str] = []
    bus.subscribe("constraint.violated", lambda payload: received.append(payload["constraint_id"]))
    bus.publish("constraint.updated", {"constraint_id": "min_clearance", "spec": {"mm": 0.3}})
    bus.publish("constraint.violated", {"constraint_id": "min_clearance", "severity": "error"})
    assert received == ["min_clearance"] and len(bus.violation_history()) == 2
    print("[5] ConstraintBus OK — historique et callbacks opérationnels")

    # 6) parse_netlist : s-expression KiCad minimale ---------------------------
    netlist = """
    (export (version "E")
      (components
        (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
        (comp (ref "C1") (value "100nF") (footprint "Capacitor_SMD:C_0402_1005Metric")))
      (nets
        (net (code "1") (name "GND")
          (node (ref "R1") (pin "1")) (node (ref "C1") (pin "2")))
        (net (code "2") (name "+3V3")
          (node (ref "R1") (pin "2")) (node (ref "C1") (pin "1")))))"""
    g_netlist = parse_netlist(netlist)
    assert g_netlist.get("R1").bbox == (1.6, 0.8)          # 0603 détecté
    assert g_netlist.net_of("R1", "1").net_id == "GND"
    assert set(g_netlist.nets) == {"GND", "_3V3"}
    g_json = parse_netlist('{"components": [{"ref": "U1", "footprint": "SOIC-8"}],'
                           '"nets": [{"name": "SDA", "pins": [["U1", "5"], ["R2", "1"]]}]}')
    assert g_json.get("U1").bbox == (4.9, 3.9) and g_json.net_of("U1", "5").name == "SDA"
    print(f"[6] parse_netlist OK — s-expr: {g_netlist.stats()['nets']} nets, "
          f"JSON: {g_json.stats()['components']} composants")

    # 7) parse_schematic + parse_pcb -------------------------------------------
    g_sch = parse_schematic({
        "components": [{"ref": "R1", "value": "10k"}, {"ref": "C1"}, {"ref": "C2"}],
        "wires": [["R1", "1", "C1", "1"], ["C1", "1", "C2", "1"],
                  ["R1", "2", "C1", "2"]],
    })
    assert g_sch.net_of("R1", "1") is g_sch.net_of("C2", "1")   # fusion transitifs
    g_pcb = parse_pcb({
        "project_id": "sess1", "board_size": [50.0, 40.0],
        "components": [{"ref": "U1", "footprint": "SOIC-8", "x": 25.0, "y": 20.0, "placed": True}],
        "nets": [{"net_id": "N1", "pins": [["U1", "1"], ["U1", "2"]], "routed": True}],
        "routes": [{"net_id": "N1", "points": [[25, 20], [30, 20], [30, 25]],
                    "layer": 0, "width_mm": 0.25}],
    })
    assert g_pcb.get_net("N1").path.length() > 0 and g_pcb.get("U1").placed
    print(f"[7] parse_schematic/parse_pcb OK — schematic nets={len(g_sch.nets)}, "
          f"pcb wire={g_pcb.total_wire_length():.1f}mm")

    # 8) NLToSkidl : template déterministe -> build_graph ----------------------
    script = NLToSkidl().translate("esp32 avec capteur BME680 sur USB-C")
    assert "ESP32" in script.code and script.components and script.nets
    g_skidl = NLToSkidl().build_graph(script)
    refs = set(g_skidl.components)
    assert "U1" in refs and any(r.startswith("J") for r in refs)
    assert {"PWR", "GND", "I2C_SDA", "I2C_SCL"} <= set(g_skidl.nets)
    report_skidl = engine.evaluate(g_skidl)
    print(f"[8] NLToSkidl OK — {len(g_skidl.components)} composants, "
          f"{len(g_skidl.nets)} nets, {len(report_skidl.violations)} violations détectées")

    # 9) constraint_extractor + component_lib_matcher --------------------------
    constraints = extract("4 layers, impedance 50 ohm, min trace 0.2mm, cost under 30, "
                          "JLCPCB, keep GND plane, thermal")
    ids = {c.constraint_id for c in constraints}
    assert {"param.layer_count", "impedance_target", "min_trace_width",
            "max_cost_usd", "mfg.jlcpcb_capability", "param.ground_plane",
            "thermal_hotspot"} <= ids
    lib = ComponentLibMatcher()
    hits = lib.match("esp32 wifi module")
    assert hits and lib.resolve("AMS1117-3.3") is not None
    print(f"[9] extractor/lib OK — {len(constraints)} contraintes, "
          f"lib match #1 = {hits[0].mpn} ({len(lib.all())} entrées)")

    print("DESIGN_CORE OK")


if __name__ == "__main__":
    main()
