#!/usr/bin/env bash
# =============================================================================
# PCB_AI_DESIGNER_V3 — déploiement k8s via kustomize
#   ./scripts/deployment/deploy_k8s.sh <development|staging|production> [--dry-run]
# Valide l'overlay (kustomize build) avant application, puis kubectl apply -k.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
K8S_DIR="${REPO_ROOT}/.infra/kubernetes"
ENVIRONMENT="${1:-}"
DRY_RUN="${2:-}"

usage() {
    echo "Usage : $0 <development|staging|production> [--dry-run]"
    echo ""
    echo "Environnements disponibles :"
    ls -1 "${K8S_DIR}/environments" 2>/dev/null | sed 's/^/  - /'
}

[ -z "${ENVIRONMENT}" ] && { usage >&2; exit 1; }
OVERLAY="${K8S_DIR}/environments/${ENVIRONMENT}"
[ -d "${OVERLAY}" ] || { echo "ERREUR : overlay inconnu '${ENVIRONMENT}'" >&2; usage >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || { echo "ERREUR : kubectl introuvable" >&2; exit 1; }

echo "==> Validation de l'overlay : ${ENVIRONMENT}"
MANIFESTS="$(kubectl kustomize "${OVERLAY}")"    # échoue si YAML invalide
if command -v kustomize >/dev/null 2>&1; then
    # Double vérification indépendante de kubectl
    kustomize build "${OVERLAY}" > /dev/null
fi
echo "    manifestes valides ($(echo "${MANIFESTS}" | grep -c '^kind:') ressources)."

if [ "${DRY_RUN}" = "--dry-run" ]; then
    echo "==> --dry-run : affichage du rendu final, rien n'est appliqué."
    echo "${MANIFESTS}"
    exit 0
fi

echo "==> Contexte kubectl courant : $(kubectl config current-context)"
read -r -p "Appliquer '${ENVIRONMENT}' sur ce cluster ? [y/N] " confirm
case "${confirm}" in
    y|Y) : ;;
    *) echo "Annulé."; exit 0 ;;
esac

echo "==> kubectl apply -k ${OVERLAY}"
kubectl apply -k "${OVERLAY}"

echo ""
echo "==> État des ressources (namespace $(kubectl kustomize "${OVERLAY}" | awk '/^  namespace:/ {print $2; exit}'))"
kubectl get deployments,pods,svc,ingress -A 2>/dev/null | grep -i pcb || true

cat <<'EOF'

Déploiement soumis. Vérifier le rollout :
  kubectl -n <namespace> rollout status deployment/pcb3-api-gateway
  kubectl -n <namespace> logs -f deployment/pcb3-api-gateway --tail=100
EOF
