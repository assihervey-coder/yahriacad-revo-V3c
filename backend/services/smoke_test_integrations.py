"""Smoke test intégrations (task 2-d) — exécuter depuis la racine du repo.

PYTHONPATH=.:backend python3 backend/services/smoke_test_integrations.py
"""
from __future__ import annotations

import asyncio
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RETRY_COUNT = 5
RETRY_SLEEP_S = 30


def import_design_core_with_retry() -> None:
    """Réessaie jusqu'à 5 fois (sleep 30) tant que l'agent 2-a n'a pas fini."""
    last_exc: Exception | None = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            import services.design_core  # noqa: F401
            print(f"[1] services.design_core importé (tentative {attempt})")
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[1] design_core pas prêt ({attempt}/{RETRY_COUNT}): {exc}")
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_SLEEP_S)
    raise SystemExit(f"design_core indisponible après {RETRY_COUNT} tentatives: {last_exc}")


import_design_core_with_retry()

from shared.geometry import Point, RoutePath  # noqa: E402
from shared.utilities import configure_logging  # noqa: E402

from services.design_core import DesignGraph, Pad  # noqa: E402

configure_logging("WARNING")

# ---------------------------------------------------------------------------
# [2] Graphe de test : 4 composants + 2 nets routés (3-4 points + 1 via chacun)
# ---------------------------------------------------------------------------
g = DesignGraph(project_id="smoke-2d", name="smoke-integrations", board_size=(60.0, 40.0))
assert [ly.name for ly in g.layers] == ["F.Cu", "GND", "PWR", "B.Cu"]

g.add_component(
    "U1", value="ESP32-WROOM-32E", footprint="ESP32-WROOM", mpn="ESP32-WROOM-32E-N4",
    x=30.0, y=20.0,
    pads=[
        Pad(name="1", x=-8.9, y=-11.5, w=0.6, h=1.4, net_id="GND", layer=0),
        Pad(name="2", x=-7.6, y=-11.5, w=0.6, h=1.4, net_id="+3V3", layer=0),
        Pad(name="15", x=0.0, y=-12.9, w=0.6, h=1.4, net_id="SDA", layer=0),
        Pad(name="16", x=1.3, y=-12.9, w=0.6, h=1.4, net_id="SCL", layer=0),
    ], placed=True)
g.add_component(
    "R1", value="10k", footprint="R_0402", mpn="RC0402FR-0710KL",
    x=12.0, y=10.0, rotation=90.0,
    pads=[
        Pad(name="1", x=-0.75, y=0.0, w=0.5, h=0.55, net_id="SDA", layer=0),
        Pad(name="2", x=0.75, y=0.0, w=0.5, h=0.55, net_id="SCL", layer=0),
    ], placed=True)
g.add_component(
    "C1", value="100n", footprint="C_0402", mpn="CL05B104KO5NNNC", price_usd=0.01,
    x=45.0, y=8.0, side="bottom",
    pads=[
        Pad(name="1", x=-0.7, y=0.0, w=0.5, h=0.55, net_id="SCL", layer=3),
        Pad(name="2", x=0.7, y=0.0, w=0.5, h=0.55, net_id="GND", layer=3),
    ], placed=True)
g.add_component(
    "J1", value="BarrelJack", footprint="DIP-2", mpn="PJ-002A", price_usd=0.42,
    x=8.0, y=30.0,
    pads=[
        Pad(name="1", x=-2.0, y=0.0, w=1.0, h=1.8, net_id="+3V3", layer=0),
        Pad(name="2", x=2.0, y=0.0, w=1.0, h=1.8, net_id="GND", layer=0),
    ], placed=True)

net_sda = g.add_net(net_id="SDA", name="/SDA", pins=[("U1", "15"), ("R1", "1")])
net_sda.path = RoutePath(
    net_id="SDA",
    points=[Point(30.0, 7.1), Point(36.0, 7.1), Point(36.0, 10.0), Point(12.75, 10.0)],
    layer=0, width_mm=0.25, vias=[(Point(36.0, 7.1), 0, 3)])
net_sda.routed = True

net_scl = g.add_net(net_id="SCL", name="/SCL", pins=[("U1", "16"), ("R1", "2"), ("C1", "1")])
net_scl.path = RoutePath(
    net_id="SCL",
    points=[Point(31.3, 7.1), Point(40.0, 7.1), Point(40.0, 4.0), Point(44.3, 4.0)],
    layer=3, width_mm=0.25, vias=[(Point(40.0, 7.1), 3, 0)])
net_scl.routed = True
g.add_net(net_id="GND", name="GND", class_name="power",
          pins=[("U1", "1"), ("C1", "2"), ("J1", "2")])
g.add_net(net_id="+3V3", name="+3V3", class_name="power", pins=[("U1", "2"), ("J1", "1")])

assert len(g.components) == 4 and len(g.nets) == 4
print("[2] graph OK: 4 composants, 4 nets, 2 routés")

# ---------------------------------------------------------------------------
# [3] KiCad export → ré-import → mêmes composants
# ---------------------------------------------------------------------------
from services.pcb_plugin import export_kicad_pcb, import_kicad_pcb  # noqa: E402

kicad_text = export_kicad_pcb(g)
assert "(version 20221018)" in kicad_text
g2 = import_kicad_pcb(kicad_text)
assert set(g2.components) == set(g.components), (set(g2.components), set(g.components))
for ref in g.components:
    a, b = g.components[ref], g2.components[ref]
    assert abs(a.x - b.x) < 1e-3 and abs(a.y - b.y) < 1e-3, (ref, a.x, b.x)
    assert abs((a.rotation or 0) - (b.rotation or 0)) < 1e-3, ref
    assert a.side == b.side, ref
    assert len(a.pads) == len(b.pads), ref
assert set(g2.nets) >= {"SDA", "SCL", "GND", "+3V3"}
sda2 = g2.nets["SDA"]
assert sda2.routed and len(sda2.path.points) == 4 and len(sda2.path.vias) == 1
assert abs(sda2.path.points[2].x - 36.0) < 1e-3
assert abs(g2.board_size[0] - 60.0) < 1e-3 and abs(g2.board_size[1] - 40.0) < 1e-3
print(f"[3] KiCad round-trip OK ({len(kicad_text.splitlines())} lignes, "
      f"{len(g2.components)} composants)")

# netlist import (bonus)
NETLIST = """
(export (version "E")
  (components
    (comp (ref "R5") (value "4.7k") (footprint "R_0402")
      (property (name "MPN") (value "RC0402FR-074K7L"))))
  (nets
    (net (code "1") (name "/SDA") (node (ref "R5") (pin "1")))
    (net (code "2") (name "GND") (node (ref "R5") (pin "2")))))
"""
from services.pcb_plugin import import_kicad_netlist  # noqa: E402

g_nl = import_kicad_netlist(NETLIST)
assert "R5" in g_nl.components and g_nl.components["R5"].mpn == "RC0402FR-074K7L"
assert "SDA" in g_nl.nets and ("R5", "1") in [tuple(p) for p in g_nl.nets["SDA"].pins]
print("[3b] KiCad netlist OK")

# ---------------------------------------------------------------------------
# [4] Gerber RS-274X
# ---------------------------------------------------------------------------
from services.exporter import GerberGenerator  # noqa: E402

gerbers = GerberGenerator(g).generate()
f_cu = gerbers["smoke-integrations-F_Cu.gbr"]
b_cu = gerbers["smoke-integrations-B_Cu.gbr"]
assert "%FSLAX46Y46*%" in f_cu and "%MOMM*%" in f_cu
assert "D01" in f_cu and "D03" in f_cu and "X360000Y71000" in f_cu
assert "X300000Y71000D02" in f_cu.replace("\n", "")
assert "D03" in b_cu  # pads C1 (bottom)
assert "GND" in gerbers["smoke-integrations-GND.gbr"]
drill = gerbers["smoke-integrations.drl"]
assert "M48" in drill and "T1 C0.3" in drill and "X36.000Y7.100" in drill
assert "M02" in gerbers["smoke-integrations-Edge_Cuts.gbr"]
print(f"[4] Gerber OK: {len(gerbers)} fichiers RS-274X + Excellon")

# ---------------------------------------------------------------------------
# [5] BOM + Pick&Place CSV
# ---------------------------------------------------------------------------
from services.exporter import BOMGenerator, PickPlaceGenerator  # noqa: E402

bom_csv = BOMGenerator(g).generate_csv()
header = bom_csv.splitlines()[0]
assert header == "Ref,Qty,Value,Footprint,MPN,Description,Price", header
assert "RC0402FR-0710KL" in bom_csv and "U1" in bom_csv
bom_json = json.loads(BOMGenerator(g).generate_json())
assert isinstance(bom_json, list) and bom_json

pp_top = PickPlaceGenerator(g).generate_csv("top")
assert pp_top.splitlines()[0] == "Ref,Designator,Mid X,Mid Y,Layer,Rotation"
assert ",top," in pp_top and "U1" in pp_top and "C1" not in pp_top
pp_bot = PickPlaceGenerator(g).generate_csv("bottom")
assert "C1" in pp_bot and ",bottom," in pp_bot
print("[5] BOM/PickPlace OK (headers exacts, groupé par MPN, sides séparés)")

# ---------------------------------------------------------------------------
# [6] IPC-2581 (parse xml.etree)
# ---------------------------------------------------------------------------
from services.exporter import IPC2581Generator  # noqa: E402

ipc_xml = IPC2581Generator(g, supplier="jlcpcb").generate()
root = ET.fromstring(ipc_xml)
assert root.tag.endswith("IPC-2581")
assert root.find(".//{*}LogisticHeader") is not None
assert root.find(".//{*}Bom") is not None and root.find(".//{*}Avl") is not None
assert root.find(".//{*}StackupGroup") is not None
assert root.find(".//{*}LayerFeature") is not None
print(f"[6] IPC-2581 OK ({len(ipc_xml)} chars, XML valide)")

# ---------------------------------------------------------------------------
# [7] ManufacturingIntelligence.analyze → cost.total > 0
# ---------------------------------------------------------------------------
from services.manufacturing_intelligence import ManufacturingIntelligence  # noqa: E402

report = ManufacturingIntelligence("jlcpcb").analyze(g)
assert report["cost"]["total_usd"] > 0, report["cost"]
assert report["factory"] == "jlcpcb"
assert 0.0 < report["yield"]["expected_yield"] <= 1.0
assert report["dfm_feedback"] and "min_trace_mm" in report["dfm_feedback"]
print(f"[7] Manufacturing OK: total={report['cost']['total_usd']}$, "
      f"yield={report['yield']['expected_yield']}")

# ---------------------------------------------------------------------------
# [8] FirmwareBridge → header C
# ---------------------------------------------------------------------------
from services.firmware_bridge import FirmwareBridge  # noqa: E402

fw = FirmwareBridge().generate_all(g)
header = fw["firmware/pins.h"]
assert "#ifndef PINS_H" in header and "#define PIN_SDA" in header
assert "GPIO" in header and "U1" in header
assert 'compatible = "pcb-ai,pin-map"' in fw["firmware/app.overlay"]
assert "#define" in fw["firmware/pins_arduino.h"]
assert "SDA" in fw["firmware/pin_map.json"]

# variante STM32 : gpios PA*/PB* → snippets HAL_GPIO_Init par port
from services.firmware_bridge import generate_stm32_init, validate  # noqa: E402

stm_map = {
    "U9": {
        "5": {"net": "/SDA", "gpio": "PA9", "functions": ["GPIO", "I2C"]},
        "6": {"net": "/SCL", "gpio": "PA10", "functions": ["GPIO", "I2C"]},
        "21": {"net": "LED", "gpio": "PB8", "functions": ["GPIO", "PWM"]},
    }
}
stm_c = generate_stm32_init(stm_map)
assert "HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);" in stm_c
assert "HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);" in stm_c
assert "__HAL_RCC_GPIOA_CLK_ENABLE();" in stm_c
assert validate(stm_map) == [] or all(i.severity != "error" for i in validate(stm_map))
print(f"[8] Firmware OK: {len(fw)} artefacts (header C, overlay, arduino) + STM32 HAL")

# ---------------------------------------------------------------------------
# [9] Bonus : ODB++, package, session, altium, live host offline, facade
# ---------------------------------------------------------------------------
from services.exporter import ExportFacade, ManufacturingPackage, ODBGenerator  # noqa: E402
from services.pcb_plugin import AltiumBridge, KiCadLiveHost, SessionRestorer  # noqa: E402
from services.pcb_plugin.altium import AltiumSynchronizer  # noqa: E402

odb = ODBGenerator(g).generate()
tar_name = next(iter(odb))
assert tar_name.endswith(".odb.tgz") and len(odb[tar_name]) > 500

pkg_dir = REPO / "data" / "tmp_smoke_2d"
pkg = ManufacturingPackage(g).build(output_dir=str(pkg_dir))
assert len(pkg) >= 10 and b"%FSLAX46Y46*%" in pkg["smoke-integrations-F_Cu.gbr"]
assert "PACKAGE MANUFACTURIER" in pkg["readme.txt"].decode("utf-8")
zip_bytes = ManufacturingPackage(g).make_zip()
assert zip_bytes[:2] == b"PK"

tmp_sessions = REPO / "data" / "tmp_smoke_sessions_2d"
from services.design_core import DesignVersioning  # noqa: E402

versioning = DesignVersioning("smoke-2d")
versioning.commit(g, "révision initiale (smoke)")
restorer = SessionRestorer(base_dir=str(tmp_sessions))
restorer.save_session("tenant-x", "user-y", "smoke-2d", g, versioning)
restored = restorer.restore_session("tenant-x", "user-y", "smoke-2d")
assert restored is not None and set(restored[0].components) == set(g.components)
assert restored[1] is not None  # DesignVersioning rechargé
assert restored[1].current() is not None
assert "smoke-2d" in [s["project_id"] for s in restorer.list_sessions("tenant-x")]

bridge = AltiumBridge()
payload = bridge.export_altium(g)
tmp_json = pkg_dir / "altium_export.json"
tmp_json.write_text(json.dumps(payload), encoding="utf-8")
g_alt = bridge.import_altium(str(tmp_json))
assert set(g_alt.components) == set(g.components)
report_sync = AltiumSynchronizer(bridge).sync(g_alt)
assert report_sync.resolution == "init"

ok = asyncio.run(KiCadLiveHost("ws://localhost:59999").connect())
assert ok is False  # mode offline gracieux

facade = ExportFacade().export(g, "gerber")
assert any(k.endswith("-F_Cu.gbr") for k in facade)
print("[9] Bonus OK: ODB++, package+zip, session restore, Altium, live-host offline, facade")

# ---------------------------------------------------------------------------
print("INTEGRATIONS OK")
