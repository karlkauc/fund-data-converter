"""Serve the built SPA: static assets plus the HTML shell for known client routes.

Only paths the frontend router knows get the shell (with per-route title,
description, canonical and og:* for search engines); everything else is a plain
404, so scanners probing /wp-login.php and the like get nothing.

Content pages (``app.content``) are plain HTML documents rendered here too;
``/sitemap.xml`` lists both kinds, and the home FAQ is filled into the shell.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.content.pages import all_pages, get_page, home_faq
from app.content.render import faq_html, faq_script, render_page, render_sitemap
from app.usage.context import emit
from app.usage.events import utm_fields


@dataclass(frozen=True)
class RouteMeta:
    """Per-route <head> metadata injected into the SPA shell.

    Search engines see the shell before any JavaScript runs, so title,
    description and canonical must already be right in the served HTML;
    otherwise every route looks like a duplicate of "/".
    """

    title: str
    description: str


_HOME = (
    "Free online converter for fund data: FinDatEx Tripartite Template (Solvency II TPT V7 and V8), "
    "FundsXML 4 and openfunds, as Excel, CSV or XML, in every direction. No login, files not stored."
)

# Keep in sync with ROUTES and TITLES in frontend/src/lib/router.ts.
ROUTE_META: dict[str, RouteMeta] = {
    "": RouteMeta("Fund Data Converter – TPT V7/V8, FundsXML 4 and openfunds (Free)", _HOME),
    "fundsxml-to-tpt": RouteMeta(
        "FundsXML to TPT Converter – FundsXML 4 to Tripartite Template Excel/CSV",
        "Convert FundsXML 4 documents into Solvency II TPT V7 or V8 files as Excel (XLSX) or CSV, one "
        "portfolio per share class. Free, no login, files not stored.",
    ),
    "openfunds-to-fundsxml": RouteMeta(
        "openfunds to FundsXML Converter – OFST fields, holdings and EMT/EPT/EET to FundsXML 4",
        "Convert openfunds files (XLSX, CSV) into FundsXML 4: share class static data, NAVs, portfolio "
        "holdings and the EMT, EPT, EET and EFT template fields. Lossless, free, files not stored.",
    ),
    "fundsxml-to-openfunds": RouteMeta(
        "FundsXML to openfunds Converter – FundsXML 4 to openfunds Excel/CSV",
        "Convert FundsXML 4 documents into openfunds files with OF-ID columns: one row per share "
        "class plus a holdings sheet. Free, no login, files not stored.",
    ),
    "tpt-to-openfunds": RouteMeta(
        "TPT to openfunds Converter – Tripartite Template to openfunds holdings (lossless)",
        "Convert Solvency II TPT V7/V8 files into openfunds: share class data and OFPH holdings, with "
        "every TPT field kept. Free, no login, files not stored.",
    ),
    "openfunds-to-tpt": RouteMeta(
        "openfunds to TPT Converter – openfunds holdings to Tripartite Template V7/V8",
        "Convert openfunds portfolio holdings (OFPH) and share class data into a Solvency II TPT V7 or "
        "V8 file as Excel or CSV. Free, no login, files not stored.",
    ),
    "mapping": RouteMeta(
        "TPT ⇄ FundsXML field mapping – every TPT V7/V8 field and its FundsXML path",
        "Which FundsXML 4 element each FinDatEx TPT field and each openfunds field maps to: the "
        "Solvency II TPT block, fund, share class, position, asset master data and EMT/EPT/EET.",
    ),
    "api-docs": RouteMeta(
        "Fund Data Converter API – convert from scripts with curl, PowerShell or Python",
        "One HTTP request converts a TPT file to FundsXML 4 or back and returns the file plus a "
        "report: validation, issues, data loss. No account, no API key.",
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
_CANONICAL_RE = re.compile(r'(<link\s+rel="canonical"\s+href=")[^"]*(")', re.S)
_OG_RE = {
    key: re.compile(rf'(<meta\s+property="og:{key}"\s+content=")[^"]*(")', re.S)
    for key in ("title", "description", "url")
}
# index.html names the default origin; the deployed one comes from SITE_ORIGIN.
_ORIGIN_PLACEHOLDER = "https://www.fund-data-converter.eu"
_FAQ_MARKER = "<!--faq-->"
_FAQ_JSONLD_MARKER = "<!--faq-jsonld-->"


def render_shell(shell: str, route: str) -> str:
    """The index.html shell with title, description, canonical and og:* for ``route``."""
    meta = ROUTE_META[route]
    origin = settings.site_origin
    canonical = f"{origin}/{route}"
    title, description = html.escape(meta.title), html.escape(meta.description)
    shell = shell.replace(_ORIGIN_PLACEHOLDER, origin)
    shell = _TITLE_RE.sub(f"<title>{title}</title>", shell, count=1)
    shell = _DESCRIPTION_RE.sub(rf"\g<1>{description}\g<2>", shell, count=1)
    shell = _CANONICAL_RE.sub(rf"\g<1>{canonical}\g<2>", shell, count=1)
    for key, value in (("title", title), ("description", description), ("url", canonical)):
        shell = _OG_RE[key].sub(rf"\g<1>{value}\g<2>", shell, count=1)
    # FAQPage markup belongs to one URL only; the other routes just drop the markers.
    faq = home_faq() if route == "" else ()
    shell = shell.replace(_FAQ_MARKER, faq_html(faq), 1)
    return shell.replace(_FAQ_JSONLD_MARKER, faq_script(faq), 1)


def sitemap_urls() -> list[tuple[str, str | None]]:
    """Indexable URLs: the SPA routes, then every content page."""
    origin = settings.site_origin
    urls: list[tuple[str, str | None]] = [(f"{origin}/{route}", None) for route in ROUTE_META]
    urls += [(f"{origin}/{p.slug}", p.lastmod) for p in all_pages().values() if not p.noindex]
    return urls


def robots_txt() -> str:
    return (
        "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /go/\n\n"
        f"Sitemap: {settings.site_origin}/sitemap.xml\n"
    )


def llms_txt() -> str:
    """A plain-text map of the site for LLM crawlers (llmstxt.org)."""
    origin = settings.site_origin
    pages = [
        p
        for p in all_pages().values()
        if not p.noindex and not p.slug.startswith(("tpt/fields/", "openfunds/fields/"))
    ]
    lines = [
        "# Fund Data Converter",
        "",
        "> Free web tool and HTTP API that converts between FinDatEx Tripartite Template (Solvency II TPT "
        "V7 and V8, XLSX/CSV), FundsXML 4.2.11 and openfunds 2.13 (XLSX/CSV), in every direction. No "
        "login; files are processed in memory and not stored.",
        "",
        "## Tool",
        "",
        f"- [TPT to FundsXML]({origin}/): upload a TPT Excel or CSV file, get FundsXML 4 plus a report",
        f"- [FundsXML to TPT]({origin}/fundsxml-to-tpt): FundsXML 4 to TPT V7/V8 as XLSX or CSV",
        f"- [openfunds to FundsXML]({origin}/openfunds-to-fundsxml): openfunds static data, holdings and "
        "templates to FundsXML 4",
        f"- [FundsXML to openfunds]({origin}/fundsxml-to-openfunds): FundsXML 4 to openfunds XLSX or CSV",
        f"- [TPT to openfunds]({origin}/tpt-to-openfunds): TPT V7/V8 to openfunds holdings, lossless",
        f"- [openfunds to TPT]({origin}/openfunds-to-tpt): openfunds holdings to TPT V7/V8",
        f"- [Field mapping]({origin}/mapping): every TPT and openfunds field and its FundsXML path",
        f"- [API]({origin}/api-docs): one POST request per conversion (curl, PowerShell, Python)",
        "",
        "## Guides",
        "",
        *[f"- [{p.h1}]({origin}/{p.slug}): {p.description}" for p in pages],
        "",
    ]
    return "\n".join(lines)


class ImmutableStaticFiles(StaticFiles):
    """Vite puts a content hash in every asset name, so a file never changes under its URL."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_spa(app: FastAPI, static_path: Path) -> None:
    if (static_path / "assets").is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=static_path / "assets"), name="assets")
    static_root = static_path.resolve()
    index_file = static_path / "index.html"

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
    async def sitemap() -> Response:
        return Response(render_sitemap(sitemap_urls()), media_type="application/xml")

    @app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
    async def robots() -> Response:
        return PlainTextResponse(robots_txt())

    @app.api_route("/llms.txt", methods=["GET", "HEAD"], include_in_schema=False)
    async def llms() -> Response:
        return PlainTextResponse(llms_txt())

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "not_found"})
        if full_path and full_path != "index.html":
            candidate = (static_path / full_path).resolve()
            if static_root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        # IndexNow proves domain ownership with a key file at the root.
        if settings.indexnow_key and full_path == f"{settings.indexnow_key}.txt":
            return PlainTextResponse(settings.indexnow_key)
        route = full_path.rstrip("/")
        if route != full_path and (route in ROUTE_META or get_page(route)):
            # One URL per page: /mapping/ → /mapping, keeping the query (utm_*).
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"/{route}{query}", status_code=301)
        # HEAD comes from link checkers and monitors, not visitors.
        view = request.method == "GET"
        utm = utm_fields(request.query_params)
        page = get_page(route) if route else None
        if page is not None:
            if view:
                emit("page_view", path=f"/{route}", status_code=200, status="ok", **utm)
            return Response(
                render_page(page, settings.site_origin), media_type="text/html", headers=SHELL_HEADERS
            )
        if route not in ROUTE_META:
            return Response(status_code=404, content="Not Found", media_type="text/plain")
        if view:
            emit("page_view", path=f"/{route}", status_code=200, status="ok", **utm)
        return Response(
            render_shell(index_file.read_text(encoding="utf-8"), route),
            media_type="text/html",
            headers=SHELL_HEADERS,
        )
