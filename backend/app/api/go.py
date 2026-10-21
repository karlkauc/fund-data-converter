"""Outbound links that should be counted: ``/go/<name>`` redirects.

The converter links the sibling sites of the FreeXmlToolkit family and the
desktop app. The frontend and the content pages link to these same-origin routes
instead of the external URLs, so each click becomes a ``page_view`` row with
``path=/go/<name>`` and ``source=<name>`` – no client-side tracking.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.usage.context import emit

router = APIRouter(tags=["go"])

FREEXMLTOOLKIT_TARGETS: dict[str, str] = {
    "docs": "https://karlkauc.github.io/FreeXmlToolkit/",
    "releases": "https://github.com/karlkauc/FreeXmlToolkit/releases",
}

# The sibling sites. utm_source tells their stats where the visitor came from
# (the sites send no Referer). Keep the list identical on all sites.
SITE_KEY = "tpt-converter"
SISTER_URLS: dict[str, str] = {
    "xsd-viewer": "https://www.xsd-viewer.online/",
    "xml-viewer": "https://www.xml-viewer.online/",
    "odata-viewer": "https://www.odata-viewer.online/",
    "tpt-converter": "https://converter.status20.net/",
}


@router.get("/go/freexmltoolkit", include_in_schema=False)
async def go_freexmltoolkit(to: str = Query("docs")) -> RedirectResponse:
    key = to if to in FREEXMLTOOLKIT_TARGETS else "docs"
    emit("page_view", path=f"/go/freexmltoolkit/{key}", source="freexmltoolkit", status_code=302)
    return RedirectResponse(FREEXMLTOOLKIT_TARGETS[key], status_code=302)


@router.get("/go/{sister}", include_in_schema=False)
async def go_sister(sister: str) -> Response:
    if sister not in SISTER_URLS:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    target = SISTER_URLS[sister]
    if sister != SITE_KEY:
        target += f"?utm_source={SITE_KEY}&utm_medium=sister"
    emit("page_view", path=f"/go/{sister}", source=sister, status_code=302)
    return RedirectResponse(target, status_code=302)
