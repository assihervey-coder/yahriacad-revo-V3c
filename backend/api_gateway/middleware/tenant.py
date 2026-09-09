"""Tenant — extraction du tenant (header X-Tenant-Id ou JWT) + injection request.state.

Le tenant force le préfixe data/projects/{tenant}/ pour toutes les opérations
disque (projets, designs, exports, jobs).
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SAFE_TENANT = re.compile(r"[^a-zA-Z0-9_\-]")


class TenantMiddleware(BaseHTTPMiddleware):
    """Injecte request.state.tenant (défaut: "default")."""

    async def dispatch(self, request: Request,
                       call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        tenant = (request.headers.get("x-tenant-id") or "").strip()
        if not tenant:
            user = getattr(request.state, "user", None)
            if isinstance(user, dict):
                tenant = str(user.get("tenant") or "")
        tenant = _SAFE_TENANT.sub("", tenant)[:64] or "default"
        request.state.tenant = tenant
        return await call_next(request)


def safe_path_segment(value: str) -> str:
    """Neutralise un segment de chemin (tenant/project/user)."""
    return _SAFE_TENANT.sub("", str(value))[:64] or "default"
