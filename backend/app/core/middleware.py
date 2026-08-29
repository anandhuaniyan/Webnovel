from __future__ import annotations

import hashlib
import time
import uuid

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:100]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self' "
            "https://pagead2.googlesyndication.com https://www.googletagmanager.com; "
            "connect-src 'self' https://www.google-analytics.com; img-src 'self' data:; "
            "frame-src https://googleads.g.doubleclick.net; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 240):
        super().__init__(app)
        self.limit = requests_per_minute
        self.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith("/api") or request.url.path in {"/api/config/public"}:
            return await call_next(request)
        client = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
        minute = int(time.time() // 60)
        identity = hashlib.sha256(client.encode()).hexdigest()[:24]
        key = f"webnovel:rate:{identity}:{minute}"
        try:
            count = await self.redis.incr(key)
            if count == 1:
                await self.redis.expire(key, 120)
            if count > self.limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": "60"},
                )
        except Exception:
            # Redis availability should not make public-domain reading inaccessible.
            pass
        return await call_next(request)
