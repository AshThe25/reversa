"""HTTP hardening.

Applied to every response, including error responses - the paths that skip the
middleware are exactly the ones an attacker looks for.

The CSP is the important one and it is deliberately strict: no inline script, no
eval, no remote origins, and `frame-ancestors 'none'` so the dashboard cannot be
framed and clickjacked into executing a strategy. The frontend is built to work
under it rather than the policy being loosened to fit the frontend.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from reversa.security.ratelimit import RateLimiter

log = logging.getLogger("reversa.http")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",   # styled-jsx / tailwind runtime styles
    "img-src 'self' data:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cache-Control": "no-store",
}

# Which limiter budget a path draws from. Optimising is not the same cost as
# listing incidents, and one global limit is either too tight to use or too
# loose to protect anything.
ROUTE_CLASSES: tuple[tuple[str, str], ...] = (
    ("/api/windtunnel", "compute"),
    ("/api/experiments", "compute"),
    ("/api/incidents/scan", "compute"),
    ("/api/ai", "ai"),
    ("/api/policies", "write"),
    ("/api/webhooks", "webhook"),
)

MAX_BODY_BYTES = 512 * 1024


# Some routes cannot be classified by prefix. /api/incidents is a cheap listing
# and must stay in "read", but /api/incidents/{id}/investigation underneath it
# runs a model loop issuing live queries, and inheriting a 120/min budget from
# its parent would be the most expensive endpoint on the service wearing the
# cheapest limit.
ROUTE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("/investigation", "ai"),
)


def route_class(path: str) -> str:
    for suffix, cls in ROUTE_SUFFIXES:
        if path.endswith(suffix):
            return cls
    for prefix, cls in ROUTE_CLASSES:
        if path.startswith(prefix):
            return cls
    return "read"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request id, timing, and an error boundary that does not leak internals.

    An unhandled exception returns the request id and nothing else. Stack traces
    in a payments API response are a gift to whoever is probing it; the trace
    goes to the log, correlated by that id.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error [%s] %s %s",
                          request_id, request.method, request.url.path)
            response = JSONResponse(
                status_code=500,
                content={"error": "internal_error", "request_id": request_id},
            )

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-Id"] = request_id
        response.headers["Server-Timing"] = f"app;dur={elapsed:.1f}"
        log.info("%s %s -> %s in %.1fms [%s]", request.method,
                 request.url.path, response.status_code, elapsed, request_id)
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": "payload_too_large", "limit_bytes": MAX_BODY_BYTES},
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or RateLimiter()

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in ("/api/health",):
            return await call_next(request)

        identity = _identity(request)
        cls = route_class(request.url.path)
        decision = self.limiter.check(identity, cls)

        if not decision.allowed:
            log.warning("rate limit hit: %s on %s (%s)", identity, request.url.path, cls)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "route_class": cls,
                    "limit": decision.limit.label,
                    "retry_after_seconds": decision.retry_after,
                },
                headers={"Retry-After": str(int(decision.retry_after) + 1)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Class"] = cls
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


def _identity(request: Request) -> str:
    """Who to charge the request to.

    Session id when present, so one authenticated operator cannot dodge the
    limiter by rotating IPs. Falls back to the peer address. Deliberately does
    NOT trust X-Forwarded-For - anyone can set it, and behind a real proxy you
    configure the trusted-hop count rather than believing the header.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return f"tok:{token[-24:]}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"
