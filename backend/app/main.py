"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __version__
from app.api.content import router as content_router
from app.api.convert import router as convert_router
from app.api.feedback import router as feedback_router
from app.api.go import router as go_router
from app.api.mapping import router as mapping_router
from app.api.samples import router as samples_router
from app.api.schema import router as schema_router
from app.config import settings
from app.content.fields import field_pages
from app.content.openfunds_fields import openfunds_field_pages
from app.content.pages import register_provider
from app.rate_limit import client_ip, convert_quota, limiter, visitor_key
from app.spa import mount_spa
from app.usage.context import RequestUsage, UsageTracker, bind, emit, unbind
from app.usage.feedback import FeedbackStore
from app.usage.geoip import GeoIp
from app.usage.recorder import UsageRecorder

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")


class BufferRequestBodyMiddleware:
    """Drain the whole request body before the app responds, capped at the upload limit.

    Answering mid-upload makes uvicorn close the connection with the body half
    sent, which proxies report as 502 instead of the real 4xx. Chunks past the
    limit are not kept, so a huge body cannot fill memory; it gets a 413.
    """

    def __init__(self, app) -> None:
        self.app = app
        # Conversions being uploaded, queued or run: each holds its upload (up to the limit) in memory.
        self.conversions = 0

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        if scope.get("path") != "/api/convert":
            await self._buffered(scope, receive, send)
            return
        # Refused before the body is kept: an exhausted quota or a full queue costs no memory.
        refusal = self._refusal(Request(scope))
        if refusal is not None:
            await self._drain(receive)
            await refusal(scope, receive, send)
            return
        self.conversions += 1
        try:
            await self._buffered(scope, receive, send)
        finally:
            self.conversions -= 1

    def _refusal(self, request: Request) -> JSONResponse | None:
        visitor = visitor_key(request)
        if convert_quota.exhausted(visitor):
            wait = convert_quota.retry_after(visitor)
            return JSONResponse(
                {"detail": f"rate limit exceeded ({convert_quota.describe()}); try again in {wait} s"},
                status_code=429,
                headers={"Retry-After": str(wait), **convert_quota.headers(visitor)},
            )
        if self.conversions >= settings.max_pending_conversions:
            return JSONResponse(
                {"detail": "the converter is busy; try again in a minute"},
                status_code=503,
                headers={"Retry-After": "30"},
            )
        return None

    @staticmethod
    async def _drain(receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect" or not message.get("more_body", False):
                return

    async def _buffered(self, scope, receive, send) -> None:
        limit = settings.max_upload_bytes + 1024 * 1024  # multipart framing and form fields
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body")
            if body:
                size += len(body)
                if size <= limit:
                    chunks.append(body)
                else:
                    chunks.clear()
            if not message.get("more_body", False):
                break
        if size > limit:
            response = JSONResponse(
                {"detail": f"file exceeds the {settings.max_upload_mb} MB limit"}, status_code=413
            )
            await response(scope, receive, send)
            return
        buffered = b"".join(chunks)
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)


def build_usage_tracker() -> UsageTracker:
    """Usage statistics – inert unless USAGE_DB_URL is set (docs/USAGE_STATS.md)."""
    recorder = UsageRecorder(settings.usage_db_url, settings.usage_db_password)
    geoip = GeoIp(settings.geoip_db_path, settings.maxmind_license_key) if recorder.enabled else None
    if recorder.enabled and not settings.usage_hash_secret:
        logger.warning("USAGE_HASH_SECRET is empty; visitor hashes are only date-salted")
    return UsageTracker(recorder, geoip, settings.usage_hash_secret, settings.usage_instance)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Build the schema model and compile the XSD while the instance starts (CPU boost),
    # not on the first visitor's request.
    from app.schema.model import fundsxml_model
    from app.validate.xsd import fundsxml_schema

    await anyio.to_thread.run_sync(fundsxml_model)
    await anyio.to_thread.run_sync(fundsxml_schema)
    tracker = build_usage_tracker()
    application.state.usage = tracker
    application.state.feedback = FeedbackStore(settings.usage_db_url, settings.usage_db_password)
    await tracker.start()
    try:
        yield
    finally:
        await tracker.stop()


app = FastAPI(
    title="TPT ⇄ FundsXML Converter",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limited(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"too many requests ({exc.detail})"},
        headers={"Retry-After": "60"},
    )


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(BufferRequestBodyMiddleware)
# Text responses (HTML, JS, CSS, JSON, XML) shrink to a fifth; the proxies in front don't compress.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


# Swagger UI (/api/docs) loads its bundle from jsdelivr and starts it with an inline script;
# the strict API policy below (sandbox, default-src 'none') would leave the page blank.
DOCS_CSP = (
    "default-src 'none'; script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'"
)


# localhost/testserver: local runs and tests behave like the public host.
_INDEXED_HOSTS = {urlsplit(settings.site_origin).hostname, "localhost", "127.0.0.1", "testserver"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request failed: %s %s", request.method, request.url.path)
        response = JSONResponse(status_code=500, content={"detail": "internal error"})
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path == app.docs_url:
        response.headers["Content-Security-Policy"] = DOCS_CSP
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.hostname not in _INDEXED_HOSTS:
        # The same app answers on *.run.app and staging hosts; only SITE_ORIGIN is indexed.
        response.headers["X-Robots-Tag"] = "noindex"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def convert_rate_headers(request: Request, call_next):
    """The caller's rate limit on every /api/convert answer: success, error and 429 alike."""
    response = await call_next(request)
    if request.url.path == "/api/convert" and request.method == "POST":
        response.headers.update(convert_quota.headers(visitor_key(request)))
    return response


@app.middleware("http")
async def usage_context(request: Request, call_next):
    """Bind the visitor context for ``emit()``; outermost, so it also sees 413, 429 and 500."""
    tracker: UsageTracker | None = getattr(request.app.state, "usage", None)
    if tracker is None or not tracker.enabled:
        return await call_next(request)
    usage = RequestUsage(
        tracker=tracker,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
        # Only the converter's own frontend sends X-Client; everything else is a script.
        channel="web" if request.headers.get("x-client") == "web" else "api",
    )
    token = bind(usage)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        if request.url.path == "/api/convert" and request.method == "POST" and not usage.emitted:
            # Turned away before the handler could report it: body too large, rate limit,
            # malformed form, crash.
            code = response.status_code
            emit(
                "convert",
                status="error" if code >= 500 else "rejected",
                status_code=code,
                duration_ms=round((time.perf_counter() - start) * 1000),
            )
    finally:
        unbind(token)
    if usage.emitted:
        # Cloud Run throttles CPU after the response; give the writer a bounded
        # chance to finish while we still have it (see docs/USAGE_STATS.md).
        await tracker.recorder.drain(timeout=settings.usage_drain_seconds)
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


app.include_router(convert_router, prefix="/api")
app.include_router(content_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(go_router)
app.include_router(mapping_router, prefix="/api")
app.include_router(samples_router, prefix="/api")
app.include_router(schema_router, prefix="/api")

register_provider(field_pages)
register_provider(openfunds_field_pages)

_static = Path(settings.static_dir)
if (_static / "index.html").is_file():
    mount_spa(app, _static)
else:
    logger.info("static assets not found in %s; API-only mode", _static)
