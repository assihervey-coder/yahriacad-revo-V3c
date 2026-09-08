# Tests d'intégration

API Gateway réelle via TestClient (health, chat → job) et WorkflowEngine
(pipeline dfm_only de bout en bout).

    PYTHONPATH=.:backend python3 -m pytest tests/integration -q
