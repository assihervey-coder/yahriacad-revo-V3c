"""Tests d'intégration API — ponts EDA (KiCad / Altium / sessions) + propositions.

Chaque test tourne sur une app FastAPI réelle (TestClient) avec des dossiers
de données isolés (PCB3_DATA_DIR / SURROGATE_DATA_DIR en tmp_path).
"""
from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient avec données isolées + app fraîche."""
    monkeypatch.setenv("PCB3_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SURROGATE_DATA_DIR", str(tmp_path / "surr"))
    from api_gateway.main import app

    with fastapi_testclient.TestClient(app) as c:
        yield c


KICAD_NETLIST = '''(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32") (footprint "ESP32-WROOM-32E"))
    (comp (ref "R1") (value "10k") (footprint "R_0603_1608Metric")))
  (nets
    (net (code 1) (name "PWR")
      (node (ref "U1") (pin "1")) (node (ref "R1") (pin "2")))
    (net (code 2) (name "GND")
      (node (ref "U1") (pin "2")) (node (ref "R1") (pin "1")))))'''

ALTIUM_PONTO = {
    "components": [
        {"ref": "U1", "value": "MCU", "footprint": "QFN-16_0.5mm", "x": 10, "y": 10,
         "pads": [{"name": "1", "x": -1.5, "y": 0, "net_id": "PWR"},
                   {"name": "2", "x": 1.5, "y": 0, "net_id": "GND"}]},
    ],
    "nets": [{"net_id": "PWR"}, {"net_id": "GND"}],
    "board_size": {"w": 40, "h": 30},
}


# ------------------------------------------------------------------- KiCad
def test_kicad_import_creates_project(client):
    r = client.post("/api/v1/integrations/kicad/import",
                    json={"content": KICAD_NETLIST, "name": "test_kicad"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["project_id"].startswith("proj_")
    assert data["format"] == "kicad_netlist"
    assert data["stats"]["components"] == 2
    assert data["stats"]["nets"] == 2


def test_kicad_export_and_roundtrip(client):
    r = client.post("/api/v1/integrations/kicad/import",
                    json={"content": KICAD_NETLIST, "name": "rt"})
    pid = r.json()["project_id"]
    exp = client.get(f"/api/v1/integrations/kicad/export/{pid}?fmt=both")
    assert exp.status_code == 200
    files = exp.json()["files"]
    assert {"pcb", "netlist"} <= set(files)

    # round-trip : le .kicad_pcb exporté se ré-importe en projet complet
    with open(files["pcb"]["path"], encoding="utf-8") as fh:
        pcb_content = fh.read()
    reimport = client.post("/api/v1/integrations/kicad/import",
                           json={"content": pcb_content, "name": "rt2"})
    assert reimport.status_code == 201
    assert reimport.json()["stats"]["components"] == 2


def test_kicad_import_rejects_garbage(client):
    r = client.post("/api/v1/integrations/kicad/import",
                    json={"content": "ceci n'est pas un design"})
    assert r.status_code == 422


# ------------------------------------------------------------------ Altium
def test_altium_import_export_sync_roundtrip(client):
    imp = client.post("/api/v1/integrations/altium/import",
                      json={"payload": ALTIUM_PONTO, "name": "altium_t"})
    assert imp.status_code == 201, imp.text
    pid = imp.json()["project_id"]
    assert imp.json()["stats"]["components"] == 1

    exp = client.get(f"/api/v1/integrations/altium/export/{pid}")
    assert exp.status_code == 200
    payload = exp.json()["payload"]
    assert payload["components"][0]["ref"] == "U1"

    # round-trip export → import
    imp2 = client.post("/api/v1/integrations/altium/import",
                       json={"payload": payload, "name": "altium_rt"})
    assert imp2.status_code == 201
    assert imp2.json()["stats"]["nets"] == 2

    # sync (état distant identique → aucun conflit après init)
    sync = client.post(f"/api/v1/integrations/altium/sync/{pid}",
                       json={"remote": ALTIUM_PONTO, "resolution": "local_wins"})
    assert sync.status_code == 200
    assert sync.json()["sync"]["resolution"] in ("local_wins", "init")


def test_altium_import_empty_rejected(client):
    r = client.post("/api/v1/integrations/altium/import",
                    json={"payload": {"components": [], "nets": []}})
    assert r.status_code == 422


# ---------------------------------------------------------------- Sessions
def test_session_save_list_restore(client):
    imp = client.post("/api/v1/integrations/kicad/import",
                      json={"content": KICAD_NETLIST, "name": "sess"})
    pid = imp.json()["project_id"]

    saved = client.post(f"/api/v1/integrations/sessions/save/{pid}")
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] is True

    listed = client.get("/api/v1/integrations/sessions")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1

    restored = client.get(f"/api/v1/integrations/sessions/{pid}/restore?apply=true")
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["restored"] is True
    assert body["stats"]["components"] == 2
    assert body["applied_revision"] == 1

    # un projet sans session → 404
    other = client.post("/api/v1/integrations/kicad/import",
                        json={"content": KICAD_NETLIST, "name": "no_session"})
    pid2 = other.json()["project_id"]
    r404 = client.get(f"/api/v1/integrations/sessions/{pid2}/restore")
    assert r404.status_code == 404


# ----------------------------------------------------------------- Statut
def test_integrations_status(client):
    r = client.get("/api/v1/integrations/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"kicad", "altium", "sessions"}


# --------------------------------------------------- Surrogates β + proposals
def test_surrogates_status_and_train(client):
    status = client.get("/api/v1/simulations/surrogates/status")
    assert status.status_code == 200
    body = status.json()
    assert body["beta"] is True
    assert {"thermal", "si", "pi", "emi"} <= set(body["surrogates"])

    train = client.post("/api/v1/simulations/surrogates/train")
    assert train.status_code == 200
    assert "trained" in train.json()


def test_proposals_requires_existing_project(client):
    r = client.post("/api/v1/optimization/proj_inexistant/proposals", json={})
    assert r.status_code == 404


def test_proposals_gate_and_flow(client):
    """Porte VALID + exécution réelle de l'optimizer sur un design routé."""
    # design réel : NL → SKIDL → placement → routage
    from orchestrator.state_manager import DesignStateManager, ProjectState
    from services.parser import NLToSkidl
    from services.placement_engine.initial_placement import InitialPlacer
    from services.router.engine import RouterEngine

    state = ProjectState.create("proposals_it", tenant_id="default", user_id="anon")
    sk = NLToSkidl(None)
    g = sk.build_graph(sk.translate("carte ESP32 capteur BME680 USB-C"))
    g = InitialPlacer().place(g)
    res = RouterEngine().route_all(g)
    g = res.graph if res.graph is not None else g
    DesignStateManager().save_design("default", "anon", state.project_id, g, 0)

    r = client.post(f"/api/v1/optimization/{state.project_id}/proposals",
                    json={"objective": "balanced", "max_iters": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict_gate"] == "VALID"
    assert "autonomous_optimizer" in body["engine"]
    assert {"baseline_score", "best_score", "iterations", "proposals"} <= set(body)

    # apply=True sans amélioration stricte → rien appliqué (keeper conservatif)
    r2 = client.post(f"/api/v1/optimization/{state.project_id}/proposals",
                     json={"apply": True, "max_iters": 5})
    assert r2.status_code == 200


# ------------------------------------------------- Altium formats natifs
ALTIUM_ASCII_PCB = """PCB FILE - Protel for Windows - PCB File Version 5.0
|RECORD=2|INDEX=0|DESIGNATOR=U1|PATTERN=LQFP-48|COMMENT=STM32F103C8T6|X=11811|Y=9843|ROTATION=0|LAYER=TOPLAYER|
|RECORD=8|OWNERINDEX=0|NAME=1|X=11417|Y=9843|TOPXSIZE=59|TOPYSIZE=157|HOLESIZE=0|TOPSHAPE=ROUND|LAYER=TOPLAYER|NETNAME=PWR|
|RECORD=8|OWNERINDEX=0|NAME=44|X=12205|Y=9843|TOPXSIZE=59|TOPYSIZE=157|HOLESIZE=0|TOPSHAPE=ROUND|LAYER=TOPLAYER|NETNAME=GND|
|RECORD=2|INDEX=1|DESIGNATOR=C1|PATTERN=C_0603|COMMENT=100nF|X=15748|Y=9843|ROTATION=90|LAYER=TOPLAYER|
|RECORD=8|OWNERINDEX=1|NAME=1|X=15748|Y=10236|TOPXSIZE=39|TOPYSIZE=59|HOLESIZE=0|TOPSHAPE=RECT|LAYER=TOPLAYER|NETNAME=PWR|
|RECORD=27|NAME=PWR|NODES=2|
|RECORD=27|NAME=GND|NODES=1|
|RECORD=3|X1=11811|Y1=7874|X2=15748|Y2=7874|WIDTH=39|LAYER=TOPLAYER|NETNAME=PWR|
"""

ALTIUM_NETLIST = """[
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


def test_altium_ascii_import_creates_project(client):
    r = client.post("/api/v1/integrations/altium/import",
                    json={"content": ALTIUM_ASCII_PCB, "name": "altium_ascii_it"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["format"] == "ascii_pcb"
    assert data["source"] == "altium:ascii_pcb"
    assert data["stats"]["components"] == 2
    assert data["stats"]["nets"] == 2


def test_altium_netlist_import_creates_project(client):
    r = client.post("/api/v1/integrations/altium/import",
                    json={"content": ALTIUM_NETLIST, "name": "altium_netlist_it"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["format"] == "netlist"
    assert data["stats"]["components"] == 2
    assert data["stats"]["nets"] == 2


def test_altium_export_netlist_roundtrip(client):
    imp = client.post("/api/v1/integrations/altium/import",
                      json={"content": ALTIUM_NETLIST, "name": "altium_net_rt"})
    pid = imp.json()["project_id"]
    exp = client.get(f"/api/v1/integrations/altium/export/{pid}?fmt=netlist")
    assert exp.status_code == 200, exp.text
    body = exp.json()
    assert body["format"] == "netlist"
    assert "(PWR" in body["content"].replace("\n", "").replace(" ", "")
    assert body["file"]["path"].endswith(".net")

    imp2 = client.post("/api/v1/integrations/altium/import",
                       json={"content": body["content"], "name": "altium_net_rt2"})
    assert imp2.status_code == 201, imp2.text
    assert imp2.json()["format"] == "netlist"
    assert imp2.json()["stats"]["nets"] == 2
    assert imp2.json()["stats"]["components"] == 2


def test_altium_export_ascii_roundtrip(client):
    imp = client.post("/api/v1/integrations/altium/import",
                      json={"content": ALTIUM_ASCII_PCB, "name": "altium_asc_rt"})
    pid = imp.json()["project_id"]
    exp = client.get(f"/api/v1/integrations/altium/export/{pid}?fmt=ascii")
    assert exp.status_code == 200, exp.text
    body = exp.json()
    assert body["format"] == "ascii"
    assert body["content"].startswith("PCB FILE")
    assert body["file"]["path"].endswith(".pcb_ascii")

    imp2 = client.post("/api/v1/integrations/altium/import",
                       json={"content": body["content"], "name": "altium_asc_rt2"})
    assert imp2.status_code == 201, imp2.text
    assert imp2.json()["format"] == "ascii_pcb"
    assert imp2.json()["stats"]["components"] == 2
    assert imp2.json()["stats"]["nets"] == 2


def test_altium_import_sans_contenu_rejete(client):
    r = client.post("/api/v1/integrations/altium/import", json={})
    assert r.status_code == 422


def test_altium_export_fmt_invalide(client):
    imp = client.post("/api/v1/integrations/altium/import",
                      json={"content": ALTIUM_NETLIST, "name": "altium_fmt"})
    pid = imp.json()["project_id"]
    r = client.get(f"/api/v1/integrations/altium/export/{pid}?fmt=svg")
    assert r.status_code == 422
