"""Tests d'intégration — commande chat → pipeline (POST /api/v1/chat/commands)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api_gateway.main import app

# Tenant de test : les artefacts créés (data/projects/tests/...) sont nettoyés
# en fin de session pour ne pas polluer les données du dépôt.
_TENANT = "pytest-chat"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def teardown_module(module) -> None:  # noqa: ANN001
    shutil.rmtree(Path("data/projects") / _TENANT, ignore_errors=True)


def test_commande_acceptee_avec_job_id(client: TestClient) -> None:
    """POST chat/commands → acceptation immédiate : accepted=True + job_id."""
    response = client.post("/api/v1/chat/commands", json={
        "message": "carte capteur environnemental 2 couches, budget 30 USD",
        "tenant_id": _TENANT,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["job_id"]
    assert "plan_summary" in data


def test_commande_vide_rejetee(client: TestClient) -> None:
    """Message vide → 422 (validation pydantic, min_length=1)."""
    response = client.post("/api/v1/chat/commands", json={
        "message": "", "tenant_id": _TENANT,
    })
    assert response.status_code == 422
