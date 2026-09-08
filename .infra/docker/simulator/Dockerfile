# syntax=docker/dockerfile:1.6
# =============================================================================
# PCB_AI_DESIGNER_V3 — Image SIMULATOR (cerveau physique multi-physique)
# FROM backend + numpy/scipy optimisés (OpenBLAS) — worker : services.simulator.worker
# Build : docker build -f .infra/docker/simulator/Dockerfile -t pcb3/simulator:v3.0.0 .
# =============================================================================
FROM python:3.11-slim AS deps-builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl gfortran \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -e .

COPY backend ./backend
COPY shared ./shared
RUN /opt/venv/bin/pip install -e .

# Stack scientifique optimisée : numpy/scipy binaires OpenBLAS pré-compilées
RUN /opt/venv/bin/pip install --only-binary=:all: numpy scipy numba

# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="pcb3-simulator" \
      org.opencontainers.image.description="Simulateurs thermique/SI/PI/EM de PCB_AI_DESIGNER_V3" \
      org.opencontainers.image.version="3.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    SIM_MAX_WORKERS=4 \
    OMP_NUM_THREADS=4

RUN apt-get update && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pcb3 \
    && useradd --uid 10001 --gid pcb3 --shell /usr/sbin/nologin --create-home pcb3

COPY --from=deps-builder /opt/venv /opt/venv
COPY --chown=10001:10001 backend /app/backend
COPY --chown=10001:10001 shared /app/shared
COPY --chown=10001:10001 pyproject.toml /app/pyproject.toml
RUN mkdir -p /app/data && chown -R 10001:10001 /app/data

USER 10001:10001
WORKDIR /app
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "services.simulator.worker"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
