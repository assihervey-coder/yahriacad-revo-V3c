# syntax=docker/dockerfile:1.6
# =============================================================================
# PCB_AI_DESIGNER_V3 — Image FRONTEND Next.js
# Contexte de build : ./frontend  (dockerfile : ../.infra/docker/frontend/Dockerfile)
# Multi-stage node:20-alpine : deps (npm ci) → build (next build) → runner node.
# PAS de nginx : le serveur node Next.js (`npm start`) sert SSR + routes API.
# =============================================================================
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# -----------------------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* : valeurs de build (surchargeables via --build-arg)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
RUN npm run build

# -----------------------------------------------------------------------------
FROM node:20-alpine AS runner
LABEL org.opencontainers.image.title="pcb3-frontend" \
      org.opencontainers.image.description="Frontend Next.js de PCB_AI_DESIGNER_V3" \
      org.opencontainers.image.version="3.0.0"

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10001 -S pcb3 && adduser -u 10001 -S -G pcb3 pcb3

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/node_modules ./node_modules
COPY --from=builder --chown=10001:10001 /app/.next ./.next
COPY --from=builder --chown=10001:10001 /app/public ./public
COPY --from=builder --chown=10001:10001 /app/package.json ./package.json
# next.config.ts (si présent) pour respecter la config de build
COPY --from=builder --chown=10001:10001 /app/next.config.ts* ./

USER 10001:10001
EXPOSE 3000

# Serveur de production Next.js (SSR + routes)
CMD ["npm", "start"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget -qO- http://127.0.0.1:3000/ >/dev/null 2>&1 || exit 1
