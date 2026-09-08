# Images Docker de PCB_AI_DESIGNER_V3

- `backend/Dockerfile` → `pcb3/backend` : image de base Python (api_gateway FastAPI :8000, orchestrator, services), `PYTHONPATH=/app:/app/backend`, non-root, healthcheck `/health`.
- `ai/`, `simulator/`, `router/Dockerfile` → dérivées de la base (`+ torch CPU` / `+ numpy-scipy OpenBLAS` / base légère), chacune lançant son worker (`services.ai_engine.worker`, `services.simulator.worker`, `services.router.worker`).
- `frontend/Dockerfile` → `pcb3/frontend` : Next.js multi-stage node:20-alpine (`npm ci` → `next build` → runner standalone `node server.js`), contexte `./frontend`.
- `docker_toolchain/toolchains/` → `pcb3/toolchain-kicad` (kicad-cli exports EDA), `pcb3/toolchain-cuda` (entraînement RL GPU cu124), `pcb3/toolchain-cross` (gcc-arm-none-eabi firmware).
- Build via `scripts/deployment/build_images.sh` (tags `v3.0.0`) ou `make docker-up` (stack locale complète, cf. `docker-compose.yml` racine).
