"""API Gateway PCB_AI_DESIGNER_V3 — REST + GraphQL + WebSocket + MCP.

Point d'entrée unique de la plateforme :
  - REST      : /api/v1/{projects,designs,components,simulations,optimization,exports,billing,chat}
  - GraphQL   : /graphql (strawberry si dispo, sinon moteur JSON de repli)
  - WebSocket : /ws/{project_id} (flux live du bus d'événements)
  - MCP       : /mcp (JSON-RPC 2.0 — tools + resources)
  - Health    : /health

Middlewares : rate_limit (60 req/min par IP+route) → audit → auth (JWT ou dev
anonyme) → tenant (header X-Tenant-Id ou JWT, préfixe data/projects/{tenant}/).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shared.events import get_event_bus
from shared.utilities import configure_logging, get_logger, get_settings

from api_gateway.deps import get_engine
from api_gateway.graphql import router as graphql_router
from api_gateway.mcp_server import router as mcp_router
from api_gateway.middleware import (
    AuditMiddleware,
    AuthMiddleware,
    RateLimitMiddleware,
    TenantMiddleware,
)
from api_gateway.routes import (
    billing_router,
    chat_router,
    components_router,
    designs_router,
    exports_router,
    integrations_router,
    optimization_router,
    projects_router,
    simulations_router,
)
from api_gateway.websocket import router as websocket_router
from orchestrator.common import register_main_loop
from orchestrator.workflow_engine.runner import consume_forever, ensure_chat_subscription

log = get_logger("api_gateway")

APP_TITLE = "PCB AI DESIGNER V3 — API Gateway"
APP_DESCRIPTION = (
    "Plateforme EDA AI-native : orchestration 10 agents (super agent + workflow "
    "engine), design core, cerveaux symbolique/décision/physique, exports de "
    "fabrication. REST + GraphQL + WebSocket + MCP."
)
APP_VERSION = "3.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise le bus, le registre d'agents et le runner de workflow."""
    configure_logging()
    register_main_loop(asyncio.get_running_loop())
    bus = get_event_bus()
    ensure_chat_subscription(bus)

    engine = get_engine()
    app.state.engine = engine
    app.state.agents = engine.agents
    app.state.bus = bus
    runner_task = asyncio.create_task(consume_forever(engine), name="api-runner")
    app.state.runner_task = runner_task

    log.info("API Gateway prête — %d agents enregistrés, bus=%s",
             len(engine.agents), type(bus).__name__)
    try:
        yield
    finally:
        runner_task.cancel()
        with suppress(asyncio.CancelledError):
            await runner_task
        log.info("API Gateway arrêtée")


app = FastAPI(
    title=APP_TITLE,
    description=APP_DESCRIPTION,
    version=APP_VERSION,
    lifespan=lifespan,
)

# --- Middlewares (le DERNIER ajouté est le PLUS EXTERNE) ---------------------
app.add_middleware(TenantMiddleware)     # 4) tenant (le plus interne)
app.add_middleware(AuthMiddleware)       # 3) auth JWT / dev anonyme
app.add_middleware(AuditMiddleware)      # 2) audit structuré
app.add_middleware(RateLimitMiddleware)  # 1) rate limit 60 req/min
app.add_middleware(                      # 0) CORS (le plus externe)
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers -----------------------------------------------------------------
app.include_router(projects_router)
app.include_router(designs_router)
app.include_router(components_router)
app.include_router(simulations_router)
app.include_router(optimization_router)
app.include_router(exports_router)
app.include_router(billing_router)
app.include_router(chat_router)
app.include_router(integrations_router)
app.include_router(graphql_router)
app.include_router(websocket_router)
app.include_router(mcp_router)


# --- Health + erreurs ---------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Sonde de vie."""
    return {"status": "ok", "version": APP_VERSION}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("erreur non gérée sur %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "code": "internal_error",
        "message": str(exc)[:300],
    })


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("api_gateway.main:app", host="0.0.0.0", port=8000,
                log_level=settings.log_level.lower())
