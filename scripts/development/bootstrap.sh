#!/usr/bin/env bash
# =============================================================================
# PCB_AI_DESIGNER_V3 — bootstrap de l'environnement de développement
#   ./scripts/development/bootstrap.sh
# Crée le venv, installe le backend (édition) + les deps dev, prépare .env,
# installe les dépendances frontend.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${REPO_ROOT}/.venv"
PY="${PYTHON:-python3}"

cd "${REPO_ROOT}"

echo "==> [1/5] Environnement virtuel (${VENV})"
if [ ! -d "${VENV}" ]; then
    "${PY}" -m venv "${VENV}"
    echo "    venv créé."
else
    echo "    venv déjà présent — réutilisé."
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"

echo "==> [2/5] Installation backend : pip install -e \".[dev]\""
pip install --upgrade pip >/dev/null
pip install -e ".[dev]"

echo "==> [3/5] Fichier .env"
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "    .env créé depuis .env.example (compléter les clés API si besoin)."
else
    echo "    .env déjà présent — inchangé."
fi

echo "==> [4/5] Dépendances frontend (npm install)"
if [ -d frontend ]; then
    (cd frontend && npm install --no-audit --no-fund)
else
    echo "    ! dossier frontend/ absent — étape ignorée."
fi

echo "==> [5/5] Vérification rapide (imports plateforme)"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/backend"
"${VENV}/bin/python" -c "from services.design_core import DesignGraph; print('    design_core OK —', DesignGraph().name)"

cat <<'EOF'

Bootstrap terminé. Pour démarrer :

    source .venv/bin/activate
    ./scripts/development/run_dev.sh          # backend + frontend + worker

Ou séparément :
    make backend     # API Gateway FastAPI   http://localhost:8000
    make frontend    # Next.js               http://localhost:3000
    make worker      # orchestrateur (runner)
EOF
