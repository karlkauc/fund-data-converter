"""Serve the built SPA: static assets plus the HTML shell for known client routes.

Only paths the frontend router knows get the shell (with per-route title and
description for search engines); everything else is a plain 404, so scanners
probing /wp-login.php and the like get nothing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles


@dataclass(frozen=True)
class RouteMeta:
    title: str
    description: str


_HOME = (
    "Free online converter for FinDatEx TPT (Tripartite Template V7 and V8) files to FundsXML 4 "
    "and back. Excel or CSV in, schema-valid FundsXML out – no login, nothing stored."
)

# Keep in sync with ROUTES in frontend/src/lib/router.ts.
ROUTE_META: dict[str, RouteMeta] = {
    "": RouteMeta("TPT ⇄ FundsXML Converter – Tripartite Template V7/V8 to FundsXML 4", _HOME),
    "fundsxml-to-tpt": RouteMeta(
        "FundsXML to TPT Converter – FundsXML 4 to Tripartite Template (XLSX, CSV)",
        "Convert FundsXML 4 documents into TPT V7 or V8 files as Excel or CSV. " + _HOME,
    ),
    "mapping": RouteMeta(
        "TPT ⇄ FundsXML field mapping – every TPT V7/V8 field and its FundsXML path",
        "Which FundsXML 4 element each FinDatEx TPT field maps to: the Solvency II TPT block, "
        "fund, position and asset master data.",
    ),
}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; object-src 'none'; frame-ancestors 'none'"
)

SHELL_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cache-Control": "no-cache",
}

_TITLE_RE = re.compile(r"<title>.*?</title>", re.S)
_DESCRIPTION_RE = re.compile(r'(<meta\s+name="description"\s+content=")[^"]*(")', re.S)


def render_shell(shell: str, route: str) -> str:
    meta = ROUTE_META[route]
    shell = _TITLE_RE.sub(f"<title>{html.escape(meta.title)}</title>", shell, count=1)
    return _DESCRIPTION_RE.sub(rf"\g<1>{html.escape(meta.description)}\g<2>", shell, count=1)


def mount_spa(app: FastAPI, static_path: Path) -> None:
    if (static_path / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")
    static_root = static_path.resolve()
    index_file = static_path / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "not_found"})
        if full_path and full_path != "index.html":
            candidate = (static_path / full_path).resolve()
            if static_root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        route = full_path.rstrip("/")
        if route not in ROUTE_META:
            return Response(status_code=404, content="Not Found", media_type="text/plain")
        return Response(
            render_shell(index_file.read_text(encoding="utf-8"), route),
            media_type="text/html",
            headers=SHELL_HEADERS,
        )
