"""Authentification JWT — mode dev anonyme si aucun secret réel n'est configuré.

Si JWT_SECRET (ou JWT_SECRET_KEY) est défini (≠ "dev-secret"), le middleware
exige un Bearer JWT valide et extrait {tenant, user, scopes} des claims.
Sinon : identité anonyme {"tenant": "default", "user": "anon", "scopes": ["*"]}.
"""
from __future__ import annotations

import os
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shared.utilities import get_logger

log = get_logger("api.auth")

DEV_IDENTITY = {"tenant": "default", "user": "anon", "scopes": ["*"]}


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET") or os.getenv("JWT_SECRET_KEY") or ""
    return secret if secret and secret != "dev-secret" else ""


class AuthMiddleware(BaseHTTPMiddleware):
    """Vérifie le JWT si configuré, sinon injecte l'identité de dev."""

    async def dispatch(self, request: Request,
                       call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        secret = _jwt_secret()
        if not secret:
            request.state.user = dict(DEV_IDENTITY)
            request.state.auth_mode = "dev-anonymous"
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse(status_code=401,
                                content={"code": "unauthorized",
                                         "message": "Header Authorization: Bearer <JWT> requis"})
        token = header[7:].strip()
        try:
            import jwt

            claims = jwt.decode(token, secret, algorithms=["HS256"])
        except Exception as exc:
            return JSONResponse(status_code=401,
                                content={"code": "unauthorized",
                                         "message": f"JWT invalide: {exc}"})
        scopes = claims.get("scopes") or ["design:read"]
        if isinstance(scopes, str):
            scopes = [scopes]
        request.state.user = {
            "tenant": str(claims.get("tenant") or claims.get("tid") or "default"),
            "user": str(claims.get("sub") or claims.get("user") or "user"),
            "scopes": list(scopes),
        }
        request.state.auth_mode = "jwt"
        return await call_next(request)


def user_scopes(request: Request) -> list:
    """Scopes de l'identité courante (["*"] en dev)."""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict):
        return list(user.get("scopes") or [])
    return ["*"]
