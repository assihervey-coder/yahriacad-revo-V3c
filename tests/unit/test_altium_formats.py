"""Tests unitaires — formats Altium natifs (PCB ASCII, PcbDoc binaire, netlist)."""
from __future__ import annotations

import struct

import pytest

from services.pcb_plugin.altium.ascii_pcb import parse_ascii_pcb, write_ascii_pcb
from services.pcb_plugin.altium.formats import (
    ALTIUM_TO_MM,
    is_ole_document,
    mm_to_altium,
    parse_record,
    parse_records_binary,
    payload_to_graph_dict,
    to_mm,
)
from services.pcb_plugin.altium.netlist_io import parse_netlist, write_netlist
from services.pcb_plugin.altium.pcbdoc import parse_pcbdoc_stream

ASCII_PCB = """PCB FILE - Protel for Windows - PCB File Version 5.0
|RECORD=2|INDEX=0|DESIGNATOR=U1|PATTERN=LQFP-48|COMMENT=STM32F103C8T6|X=11811|Y=9843|ROTATION=0|LAYER=TOPLAYER|
|RECORD=8|OWNERINDEX=0|NAME=1|X=11417|Y=9843|TOPXSIZE=59|TOPYSIZE=157|HOLESIZE=0|TOPSHAPE=ROUND|LAYER=TOPLAYER|NETNAME=PWR|
|RECORD=8|OWNERINDEX=0|NAME=44|X=12205|Y=9843|TOPXSIZE=59|TOPYSIZE=157|HOLESIZE=0|TOPSHAPE=ROUND|LAYER=TOPLAYER|NETNAME=GND|
|RECORD=2|INDEX=1|DESIGNATOR=C1|PATTERN=C_0603|COMMENT=100nF|X=15748|Y=9843|ROTATION=90|LAYER=TOPLAYER|
|RECORD=8|OWNERINDEX=1|NAME=1|X=15748|Y=10236|TOPXSIZE=39|TOPYSIZE=59|HOLESIZE=0|TOPSHAPE=RECT|LAYER=TOPLAYER|NETNAME=PWR|
|RECORD=27|NAME=PWR|NODES=2|
|RECORD=27|NAME=GND|NODES=1|
|RECORD=3|X1=11811|Y1=7874|X2=15748|Y2=7874|WIDTH=39|LAYER=TOPLAYER|NETNAME=PWR|
|RECORD=4|X=13779|Y=7874|DIAMETER=59|HOLESIZE=31|LAYERPAIR=TopLayer-BottomLayer|NETNAME=PWR|
"""

NETLIST_PROTEL = """Protel netlist
[
U1
LQFP-48
STM32F103C8T6
]
[
C1
C_0603
100nF
]

(
PWR
U1-1
C1-1
)
(
GND
U1-44
)
"""


# ------------------------------------------------------------------ formats
def test_parse_record():
    rec = parse_record("|RECORD=2|DESIGNATOR=U1|X=11811|*")
    assert rec == {"RECORD": "2", "DESIGNATOR": "U1", "X": "11811"}
    assert parse_record("") == {}
    assert parse_record("|sans-egalite|RECORD=27|") == {"RECORD": "27"}


def test_unites_altium():
    # 1 pouce = 25.4 mm ; 10000 unités = 1 pouce
    assert to_mm("10000") == pytest.approx(25.4, abs=1e-3)
    assert to_mm("11811") == pytest.approx(29.99994, abs=1e-3)
    assert mm_to_altium(25.4) == 10000
    # aller-retour exact sur 1 pouce (quantification 1/10000 in sinon)
    assert ALTIUM_TO_MM * mm_to_altium(25.4) == pytest.approx(25.4, abs=1e-3)


def test_parse_records_binary_et_saut_inconnu():
    recs = [
        b"|RECORD=2|INDEX=0|DESIGNATOR=U1|X=11811|Y=9843|LAYER=TOPLAYER|",
        b"\x00\x01garbage sans separateur",  # record inconnu → ignoré proprement
        b"|RECORD=8|OWNERINDEX=0|NAME=1|X=11417|Y=9843|TOPXSIZE=59|TOPYSIZE=157|NETNAME=GND|",
        b"|RECORD=27|NAME=GND|",
    ]
    stream = b"".join(struct.pack(">H", len(r)) + r for r in recs)
    parsed = parse_records_binary(stream)
    assert [p.get("RECORD") for p in parsed] == ["2", "8", "27"]
    assert parsed[0]["DESIGNATOR"] == "U1"


def test_is_ole_document():
    assert is_ole_document(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8)
    assert not is_ole_document(b"|RECORD=1|")


# ------------------------------------------------------------------ PCB ASCII
def test_parse_ascii_pcb():
    payload = parse_ascii_pcb(ASCII_PCB)
    comps = {c["ref"]: c for c in payload["components"]}
    assert set(comps) == {"U1", "C1"}
    assert comps["U1"]["footprint"] == "LQFP-48"
    assert comps["U1"]["value"] == "STM32F103C8T6"
    assert comps["U1"]["x"] == pytest.approx(30.0, abs=0.01)
    assert comps["C1"]["rotation"] == pytest.approx(90.0)
    # pads + connectivité depuis NETNAME
    u1_pads = {p["name"]: p for p in comps["U1"]["pads"]}
    assert u1_pads["1"]["net_id"] == "PWR"
    assert u1_pads["44"]["net_id"] == "GND"
    nets = {n["net_id"]: n for n in payload["nets"]}
    assert sorted(nets["PWR"]["pins"]) == [["C1", "1"], ["U1", "1"]]
    assert nets["GND"]["pins"] == [["U1", "44"]]
    assert nets["PWR"]["routed"] is True  # piste + via présents
    assert len(nets["PWR"]["path"]["points"]) == 2
    assert len(nets["PWR"]["path"]["vias"]) == 1
    assert payload["board_size"][0] > 0


def test_ascii_pcb_roundtrip():
    payload = parse_ascii_pcb(ASCII_PCB)
    text = write_ascii_pcb(payload)
    reparsed = parse_ascii_pcb(text)
    assert {c["ref"] for c in reparsed["components"]} == {"U1", "C1"}
    orig_nets = {n["net_id"]: sorted(map(tuple, n.get("pins", [])))
                 for n in payload["nets"]}
    re_nets = {n["net_id"]: sorted(map(tuple, n.get("pins", [])))
               for n in reparsed["nets"]}
    assert re_nets == orig_nets
    assert re_nets["PWR"] == [("C1", "1"), ("U1", "1")]
    assert {n["net_id"]: n["routed"] for n in reparsed["nets"]} == \
           {n["net_id"]: n["routed"] for n in payload["nets"]}


def test_payload_to_graph_dict():
    payload = {"components": [{"ref": "U1"}], "nets": [{"net_id": "GND"}],
               "board_size": {"w": 40, "h": 30}}
    data = payload_to_graph_dict(payload, "essai")
    assert data["name"] == "essai"
    assert data["board_size"] == [40, 30]
    assert data["components"][0]["ref"] == "U1"


# ------------------------------------------------------------------ netlist
def test_parse_netlist():
    payload = parse_netlist(NETLIST_PROTEL)
    comps = {c["ref"]: c for c in payload["components"]}
    assert set(comps) == {"U1", "C1"}
    assert comps["U1"]["footprint"] == "LQFP-48"
    assert comps["U1"]["value"] == "STM32F103C8T6"
    nets = {n["net_id"]: n for n in payload["nets"]}
    assert sorted(nets["PWR"]["pins"]) == [["C1", "1"], ["U1", "1"]]
    assert nets["GND"]["pins"] == [["U1", "44"]]
    # pads reconstruits depuis les nœuds
    u1_pads = {p["name"]: p["net_id"] for p in comps["U1"]["pads"]}
    assert u1_pads == {"1": "PWR", "44": "GND"}


def test_netlist_roundtrip():
    payload = parse_netlist(NETLIST_PROTEL)
    text = write_netlist(payload)
    reparsed = parse_netlist(text)
    nets = {n["net_id"]: sorted(map(tuple, n.get("pins", []))) for n in payload["nets"]}
    re_nets = {n["net_id"]: sorted(map(tuple, n.get("pins", [])))
               for n in reparsed["nets"]}
    assert re_nets == nets
    assert {c["ref"] for c in reparsed["components"]} == {"U1", "C1"}


# ------------------------------------------------------------------ binaire
def _binary_stream() -> bytes:
    recs = [
        b"|RECORD=2|INDEX=0|DESIGNATOR=U1|PATTERN=LQFP-48|X=11811|Y=9843"
        b"|LAYER=TOPLAYER|",
        b"|RECORD=8|OWNERINDEX=0|NAME=1|X=11417|Y=9843|TOPXSIZE=59|TOPYSIZE=157"
        b"|LAYER=TOPLAYER|NETNAME=PWR|",
        b"|RECORD=8|OWNERINDEX=0|NAME=44|X=12205|Y=9843|TOPXSIZE=59|TOPYSIZE=157"
        b"|LAYER=TOPLAYER|NETNAME=GND|",
        b"|RECORD=27|NAME=PWR|",
        b"|RECORD=27|NAME=GND|",
    ]
    return b"".join(struct.pack(">H", len(r)) + r for r in recs)


def test_parse_pcbdoc_stream():
    payload = parse_pcbdoc_stream(_binary_stream())
    assert len(payload["components"]) == 1
    comp = payload["components"][0]
    assert comp["ref"] == "U1"
    assert comp["footprint"] == "LQFP-48"
    assert comp["side"] == "top"
    assert {p["name"]: p["net_id"] for p in comp["pads"]} == {"1": "PWR", "44": "GND"}
    assert {n["net_id"]: sorted(map(tuple, n["pins"])) for n in payload["nets"]} == \
           {"PWR": [("U1", "1")], "GND": [("U1", "44")]}


def test_parse_pcbdoc_stream_tronque():
    stream = _binary_stream()
    # coupure DANS le 2e record (pad) : le 1er reste décodable proprement
    (first_len,) = struct.unpack_from(">H", stream, 0)
    payload = parse_pcbdoc_stream(stream[:2 + first_len + 2 + 10])
    assert len(payload["components"]) == 1
    assert payload["components"][0]["ref"] == "U1"


# ------------------------------------------------------------------ bridge
def test_import_auto_json_ascii_netlist():
    from services.pcb_plugin.altium import AltiumBridge

    bridge = AltiumBridge()
    graph, fmt = bridge.import_auto('{"components": [{"ref": "U1"}], "nets": []}')
    assert fmt == "json"
    assert len(graph.components) == 1

    graph2, fmt2 = bridge.import_auto(ASCII_PCB)
    assert fmt2 == "ascii_pcb"
    assert {c.ref for c in graph2.components.values()} == {"U1", "C1"}

    graph3, fmt3 = bridge.import_auto(NETLIST_PROTEL)
    assert fmt3 == "netlist"
    assert len(graph3.nets) == 2

    with pytest.raises(ValueError):
        bridge.import_auto("ceci n'est pas un format altium")


def test_bridge_exports_netlist_et_ascii():
    from services.pcb_plugin.altium import AltiumBridge

    bridge = AltiumBridge()
    graph, _fmt = bridge.import_auto(ASCII_PCB)
    netlist_text = bridge.export_netlist(graph)
    assert "(\nPWR" in netlist_text and "U1-1" in netlist_text
    ascii_text = bridge.export_ascii(graph)
    assert ascii_text.startswith("PCB FILE")
    assert "|RECORD=27|NAME=PWR|" in ascii_text
