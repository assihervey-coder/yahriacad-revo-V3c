"""Tests d'intégration — santé de l'API Gateway (GET /health)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api_gateway.main import APP_VERSION, app


def test_health_ok() -> None:
    """GET /health répond 200 avec status=ok et la version de la plateforme."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == APP_VERSION == "3.0.0"


def test_health_headers_json() -> None:
    """La sonde renvoie bien du JSON applicatif (utilisée par les probes k8s)."""
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.headers["content-type"].startswith("application/json")
