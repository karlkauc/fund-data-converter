"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __version__
from app.api.convert import router as convert_router
from app.api.mapping import router as mapping_router
from app.api.samples import router as samples_router
from app.config import settings
from app.rate_limit import limiter
from app.spa import mount_spa

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

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Build the schema model and compile the XSD while the instance starts (CPU boost),
    # not on the first visitor's request.
    from app.schema.model import fundsxml_model
    from app.validate.xsd import fundsxml_schema

    await anyio.to_thread.run_sync(fundsxml_model)
    await anyio.to_thread.run_sync(fundsxml_schema)
    yield


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
if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


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
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


app.include_router(convert_router, prefix="/api")
app.include_router(mapping_router, prefix="/api")
app.include_router(samples_router, prefix="/api")

_static = Path(settings.static_dir)
if (_static / "index.html").is_file():
    mount_spa(app, _static)
else:
    logger.info("static assets not found in %s; API-only mode", _static)
