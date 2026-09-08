# syntax=docker/dockerfile:1.6
# =============================================================================
# PCB_AI_DESIGNER_V3 — Image AI ENGINE (cerveau symbolique + décisionnel)
# FROM backend + torch CPU (roues officielles cpu) — worker : services.ai_engine.worker
# Build : docker build -f .infra/docker/ai/Dockerfile -t pcb3/ai:v3.0.0 .
# =============================================================================
FROM python:3.11-slim AS deps-builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e .

COPY backend ./backend
COPY shared ./shared
RUN /opt/venv/bin/pip install -e .

# Torch CPU : index officiel des roues CPU (~200 Mo, pas le bundle CUDA)
RUN /opt/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu

# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="pcb3-ai" \
      org.opencontainers.image.description="Cerveau IA (LLM/RAG/KG + RL) de PCB_AI_DESIGNER_V3" \
      org.opencontainers.image.version="3.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    RL_DEVICE=cpu \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4

RUN apt-get update && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pcb3 \
    && useradd --uid 10001 --gid pcb3 --shell /usr/sbin/nologin --create-home pcb3

COPY --from=deps-builder /opt/venv /opt/venv
COPY --chown=10001:10001 backend /app/backend
COPY --chown=10001:10001 shared /app/shared
COPY --chown=10001:10001 pyproject.toml /app/pyproject.toml
RUN mkdir -p /app/data/trained_models && chown -R 10001:10001 /app/data

USER 10001:10001
WORKDIR /app
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# Le worker IA consomme AGENT_TASK_ASSIGNED et émet AGENT_TASK_COMPLETED.
# Il expose aussi /health sur le port 8000 quand HEALTH_SERVER=1 (sonde k8s).
CMD ["python", "-m", "services.ai_engine.worker"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
