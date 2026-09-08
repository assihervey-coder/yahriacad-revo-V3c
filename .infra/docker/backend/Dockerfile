# syntax=docker/dockerfile:1.6
# =============================================================================
# PCB_AI_DESIGNER_V3 — Image BACKEND de base (api_gateway + orchestrator + services)
# Build : docker build -f .infra/docker/backend/Dockerfile -t pcb3/backend:v3.0.0 .
# Multi-stage : deps (pip cache) → runtime slim non-root.
# =============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Outils de compilation pour les roues sdist éventuelles (shapely, numpy…)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache des dépendances : la couche n'est invalidée que si pyproject change
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e ".[dev]" || /opt/venv/bin/pip install -e "."

# Sources (backend + shared à la racine, PYTHONPATH=/app:/app/backend)
COPY backend ./backend
COPY shared ./shared
RUN /opt/venv/bin/pip install -e . && /opt/venv/bin/pip install --no-deps -e .

# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="pcb3-backend" \
      org.opencontainers.image.description="API Gateway + orchestrator + services de PCB_AI_DESIGNER_V3" \
      org.opencontainers.image.version="3.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    DATA_DIR=/app/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pcb3 \
    && useradd --uid 10001 --gid pcb3 --shell /usr/sbin/nologin --create-home pcb3

COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 backend /app/backend
COPY --chown=10001:10001 shared /app/shared
COPY --chown=10001:10001 pyproject.toml /app/pyproject.toml
RUN mkdir -p /app/data && chown -R 10001:10001 /app/data

USER 10001:10001
WORKDIR /app
EXPOSE 8000

# Tini = réception correcte des signaux (uvicorn en PID 1 sans zombie)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
