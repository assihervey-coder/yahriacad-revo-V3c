"""Rate limiting — token bucket en mémoire par IP+route (60 req/min)."""
from __future__ import annotations

import threading
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

RATE_PER_MINUTE = 60.0
WINDOW_SECONDS = 60.0
EXEMPT_PATHS = {"/health"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket : 60 requêtes/minute par couple (IP, route)."""

    def __init__(self, app: Any = None, rate: float = RATE_PER_MINUTE) -> None:
        super().__init__(app)
        self.rate = float(rate)
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request: Request,
                       call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"
        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.rate, now))
            tokens = min(self.rate, tokens + (now - last) * (self.rate / WINDOW_SECONDS))
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return JSONResponse(status_code=429, content={
                    "code": "rate_limited",
                    "message": f"limite de {self.rate:.0f} req/min atteinte sur {request.url.path}",
                })
            self._buckets[key] = (tokens - 1.0, now)
        return await call_next(request)
