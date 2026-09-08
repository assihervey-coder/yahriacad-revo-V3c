#!/usr/bin/env bash
# =============================================================================
# PCB_AI_DESIGNER_V3 — build des 5 images Docker (tags v3.0.0 par défaut)
#   ./scripts/deployment/build_images.sh [TAG]
# Images : pcb3/{backend,ai,simulator,router,frontend}
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

TAG="${1:-v3.0.0}"
DOCKERFILE_DIR=".infra/docker"

command -v docker >/dev/null 2>&1 || { echo "ERREUR : docker introuvable" >&2; exit 1; }

build() {
    local name="$1" dockerfile="$2" context="${3:-.}"
    echo "==> build ${name}:${TAG} (${dockerfile})"
    DOCKER_BUILDKIT=1 docker build \
        --file "${DOCKERFILE_DIR}/${dockerfile}" \
        --tag "pcb3/${name}:${TAG}" \
        --tag "pcb3/${name}:latest" \
        "${context}"
}

build backend  backend/Dockerfile
build ai       ai/Dockerfile
build simulator simulator/Dockerfile
build router   router/Dockerfile
build frontend frontend/Dockerfile ./frontend

echo ""
echo "=== Images construites (tag ${TAG}) ==="
docker images "pcb3/*" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

echo ""
echo "Pousser vers un registre :"
echo "  for img in backend ai simulator router frontend; do"
echo "    docker tag pcb3/\$img:${TAG} <registry>/pcb3/\$img:${TAG} && docker push <registry>/pcb3/\$img:${TAG};"
echo "  done"
