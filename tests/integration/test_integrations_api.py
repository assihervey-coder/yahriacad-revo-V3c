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
