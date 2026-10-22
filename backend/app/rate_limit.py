"""Rate limiter shared across API routers (in-memory: one container per instance).

The client IP is the X-Forwarded-For entry the trusted proxy appended (Cloud
Run's front end), counted from the right. Entries further left are whatever
the client sent and must never be trusted.
"""

from __future__ import annotations

import ipaddress
import math
import time

from limits import RateLimitItem, parse_many
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
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


def visitor_key(request: Request) -> str:
    """What the rate limits count by: the IP, for IPv6 its /64 (one subscriber's whole block)."""
    ip = client_ip(request)
    if not ip:
        return "unknown"
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


limiter = Limiter(key_func=visitor_key, default_limits=[])


class Quota:
    """Several fixed windows (``"20/minute;200/hour"``) whose state can be reported.

    slowapi enforces limits but keeps the counters to itself; the converter tells its visitors and
    API callers how much is left (headers, the report's ``rateLimit``, ``GET /api/limits``).
    A request counts against every window, and only when all of them still have room.
    """

    def __init__(self, spec: str, scope: str) -> None:
        self.spec = spec
        self.scope = scope
        self.items = parse_many(spec)
        self._storage = MemoryStorage()
        self._limiter = FixedWindowRateLimiter(self._storage)

    def hit(self, key: str) -> bool:
        # No await in between: the check and the hit cannot interleave with another request.
        if not all(self._limiter.test(item, self.scope, key) for item in self.items):
            return False
        for item in self.items:
            self._limiter.hit(item, self.scope, key)
        return True

    def status(self, key: str) -> list[dict]:
        """Per window: limit, remaining, seconds until it resets (0 while it has not started)."""
        now = time.time()
        out = []
        for item in self.items:
            stats = self._limiter.get_window_stats(item, self.scope, key)
            started = stats.remaining < item.amount
            out.append(
                {
                    "window": _window(item),
                    "limit": item.amount,
                    "remaining": stats.remaining,
                    "resetSeconds": max(0, math.ceil(stats.reset_time - now)) if started else 0,
                }
            )
        return out

    def headers(self, key: str) -> dict[str, str]:
        """``X-RateLimit-Limit-Minute: 20`` and so on, one set per window."""
        out = {}
        for w in self.status(key):
            suffix = w["window"].title().replace(" ", "")
            out[f"X-RateLimit-Limit-{suffix}"] = str(w["limit"])
            out[f"X-RateLimit-Remaining-{suffix}"] = str(w["remaining"])
            out[f"X-RateLimit-Reset-{suffix}"] = str(w["resetSeconds"])
        return out

    def exhausted(self, key: str) -> bool:
        """True while a window has no room left (nothing is counted)."""
        return any(w["remaining"] <= 0 for w in self.status(key))

    def retry_after(self, key: str) -> int:
        """Seconds until every exhausted window has room again."""
        return max((w["resetSeconds"] for w in self.status(key) if w["remaining"] <= 0), default=1) or 1

    def describe(self) -> str:
        """``20 per minute, 200 per hour``."""
        return ", ".join(f"{item.amount} per {_window(item)}" for item in self.items)

    def reset(self) -> None:
        self._storage.reset()


def _window(item: RateLimitItem) -> str:
    name = item.GRANULARITY.name
    return name if item.multiples == 1 else f"{item.multiples} {name}s"


convert_quota = Quota(settings.convert_rate_limit, "convert")
