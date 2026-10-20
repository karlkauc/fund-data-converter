"""Rate limiter shared across API routers (in-memory: one container per instance).

The client IP is the X-Forwarded-For entry the trusted proxy appended (Cloud
Run's front end), counted from the right. Entries further left are whatever
the client sent and must never be trusted.
"""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


def client_ip(request: Request) -> str | None:
    """The visitor's IP: the ``TRUSTED_PROXY_HOPS``-th X-Forwarded-For entry from the right."""
    hops = settings.trusted_proxy_hops
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded = [part for part in forwarded if part]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else None


limiter = Limiter(key_func=lambda request: client_ip(request) or "unknown", default_limits=[])
