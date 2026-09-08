# API REST

Base : `http://localhost:8000` · Auth : `Authorization: Bearer <JWT>` (mode dev : anonyme) · Tenant : header `X-Tenant-Id`.

## Santé

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"3.0.0"}
```

## Chat — créer un design en langage naturel

```bash
curl -X POST http://localhost:8000/api/v1/chat/commands \
  -H "Content-Type: application/json" \
  -d '{"message":"Conçois une carte ESP32 4 couches 60x40mm avec un BME680 et USB-C, usine JLCPCB"}'
# {"accepted":true,"intent":"iot_sensor","plan_summary":"...","job_id":"job_...","reply":"..."}
```

Suivre l'avancement :

```bash
curl http://localhost:8000/api/v1/chat/commands/{correlation_id}/status
```

## Projets

```bash
curl -X POST http://localhost:8000/api/v1/projects -H "Content-Type: application/json" -d '{"name":"capteur-v1"}'
curl http://localhost:8000/api/v1/projects                # liste du tenant
curl http://localhost:8000/api/v1/projects/{pid}          # état + révision courante
curl -X DELETE http://localhost:8000/api/v1/projects/{pid}
```

## Designs & révisions

```bash
curl http://localhost:8000/api/v1/designs/{pid}                       # DesignSchema courant
curl http://localhost:8000/api/v1/designs/{pid}/revisions             # historique
curl -X POST http://localhost:8000/api/v1/designs/{pid}/revisions \
  -H "Content-Type: application/json" -d '{"message":"placement manuel"}'
curl -X POST http://localhost:8000/api/v1/designs/{pid}/revisions/3/restore
```

## Composants

```bash
curl "http://localhost:8000/api/v1/components/search?q=esp32"
curl http://localhost:8000/api/v1/components/ESP32-WROOM-32E
```

## Simulations

```bash
curl -X POST http://localhost:8000/api/v1/simulations/{pid} \
  -H "Content-Type: application/json" -d '{"kinds":["thermal","si","pi","em"]}'
curl http://localhost:8000/api/v1/simulations/{pid}/{job_id}
```

## Optimisation

```bash
curl -X POST http://localhost:8000/api/v1/optimization/{pid} \
  -H "Content-Type: application/json" -d '{"objective":"balanced","max_iters":30}'
curl http://localhost:8000/api/v1/optimization/{pid}/history
```

## Exports

```bash
curl -X POST http://localhost:8000/api/v1/exports/{pid} \
  -H "Content-Type: application/json" -d '{"fmt":"gerber","factory":"jlcpcb"}'
curl -OJ http://localhost:8000/api/v1/exports/{pid}          # téléchargement
```

## Facturation (crédits)

```bash
curl http://localhost:8000/api/v1/billing/credits/{tenant}
curl -X POST http://localhost:8000/api/v1/billing/consume -H "Content-Type: application/json" -d '{"tenant":"default","action":"export"}'
```

## WebSocket

```js
const ws = new WebSocket("ws://localhost:8000/ws/" + projectId);
ws.onmessage = (e) => console.log(JSON.parse(e.data));  // {type, payload, ts}
```

Types d'événements principaux : `agent.task.assigned/completed`, `placement.proposed`, `routing.proposed`, `verification.passed/failed`, `rollback.executed`, `optimization.iteration`, `export.completed`.
