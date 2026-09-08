# Setup développeur

## Prérequis

- Python 3.11+ · Node.js 20+ · Docker & Docker Compose (optionnels mais recommandés)
- Make

## Installation locale (recommandée)

```bash
git clone https://github.com/assihervey-coder/yahriacad-revo-V3c.git
cd yahriacad-revo-V3c
make setup          # venv + pip install -e ".[dev]" + npm install frontend
cp .env.example .env
```

## Lancer en mode dev

```bash
make dev            # API Gateway :8000 + worker + frontend :3000
# ou séparément :
make backend        # uvicorn api_gateway.main:app --reload --port 8000
cd frontend && npm run dev
```

Vérifier : `curl http://localhost:8000/health` → `{"status":"ok","version":"3.0.0"}` puis ouvrir http://localhost:3000.

## Stack Docker complète

```bash
make docker-up      # api + ai + simulator + router + frontend + postgres + redis + minio + prometheus + grafana + loki
make logs           # suivre les logs
make docker-down    # stop + volumes
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API Gateway | http://localhost:8000 |
| GraphQL | http://localhost:8000/graphql |
| MCP | http://localhost:8000/mcp |
| Grafana | http://localhost:3001 (admin/pcb) |
| Prometheus | http://localhost:9090 |

## Variables d'environnement principales

Voir `.env.example` — les plus importantes :

- `LLM_PROVIDER` : `mock` (défaut, aucune clé requise) / `openai` / `zai`
- `EVENT_BUS_BACKEND` : `inprocess` / `redis`
- `RL_DEVICE` : `cpu` / `cuda`
- `JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`

## Tests

```bash
make test           # unit + integration (95+ tests, ~30 s)
make test-ai        # évaluation agents IA
make lint           # ruff
make typecheck      # mypy
```

## Première exécution de bout en bout

```bash
curl -X POST http://localhost:8000/api/v1/chat/commands \
  -H "Content-Type: application/json" \
  -d '{"message":"Conçois une carte ESP32 4 couches avec BME680 et USB-C, JLCPCB"}'
```

Puis suivre l'activité des agents dans l'UI (Designer) ou via `wscat -c ws://localhost:8000/ws/{project_id}`.
