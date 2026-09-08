"""Audit — log structuré de chaque requête HTTP (method, path, status, ms, tenant)."""
from __future__ import annotations

import json
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.utilities import get_logger

audit_log = get_logger("api_gateway.audit")


class AuditMiddleware(BaseHTTPMiddleware):
    """Trace chaque requête : method, path, status, durée, tenant, ip."""

    async def dispatch(self, request: Request,
                       call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        entry = {
            "ts": round(time.time(), 3),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration_ms,
            "tenant": getattr(request.state, "tenant", None) or "default",
            "ip": request.client.host if request.client else "unknown",
        }
        audit_log.info("audit %s", json.dumps(entry, ensure_ascii=False))
        response.headers.setdefault("x-response-time-ms", str(duration_ms))
        return response
