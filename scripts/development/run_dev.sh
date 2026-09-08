#!/usr/bin/env bash
# =============================================================================
# PCB_AI_DESIGNER_V3 — démarrage du mode dev complet
#   ./scripts/development/run_dev.sh
# Lance en parallèle : API Gateway (uvicorn :8000), worker (runner),
# frontend (next dev :3000). Ctrl-C arrête tout proprement.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

VENV="${REPO_ROOT}/.venv"
if [ -x "${VENV}/bin/python" ]; then
    PYBIN="${VENV}/bin/python"
else
    PYBIN="python3"
fi

export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/backend"
export APP_ENV="${APP_ENV:-development}"
export LOG_LEVEL="${LOG_LEVEL:-DEBUG}"
export PYTHONUNBUFFERED=1

PIDS=()
cleanup() {
    echo ""
    echo "==> Arrêt des processus dev..."
    for pid in "${PIDS[@]:-}"; do
        kill "${pid}" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "==> Terminé."
}
trap cleanup EXIT INT TERM

echo "==> [1/3] API Gateway   http://localhost:8000 (docs: /docs)"
"${PYBIN}" -m uvicorn api_gateway.main:app --host 0.0.0.0 --port 8000 --reload &
PIDS+=($!)

echo "==> [2/3] Worker orchestration (runner pipeline)"
"${PYBIN}" -m orchestrator.workflow_engine.runner &
PIDS+=($!)

echo "==> [3/3] Frontend Next.js   http://localhost:3000"
if [ -d frontend ]; then
    (cd frontend && npm run dev) &
    PIDS+=($!)
else
    echo "    ! frontend/ absent — démarré sans UI."
fi

echo ""
echo "=== Dev stack PCB_AI_DESIGNER_V3 en cours (Ctrl-C pour tout arrêter) ==="
wait
