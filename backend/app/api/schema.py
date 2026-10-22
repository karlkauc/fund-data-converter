"""GET /api/schema/fundsxml.zip – the bundled FundsXML schema, handed to xml-viewer.online with a document.

The ZIP holds ``FundsXML4.xsd`` and the ``xmldsig-core-schema.xsd`` it imports, so the viewer can
validate right away. Built once from the bundled files; the frontend fetches it only on the click.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.schema.model import FUNDSXML_XSD, SCHEMA_DIR

router = APIRouter()

SCHEMA_FILES = (FUNDSXML_XSD.name, "xmldsig-core-schema.xsd")


@lru_cache(maxsize=1)
def schema_zip() -> tuple[bytes, str]:
    """The ZIP and its ETag."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in SCHEMA_FILES:
            zf.write(SCHEMA_DIR / name, name)
    data = buf.getvalue()
    return data, f'"{hashlib.sha256(data).hexdigest()[:32]}"'


@router.get("/schema/fundsxml.zip", include_in_schema=False)
async def fundsxml_schema(request: Request) -> Response:
    data, etag = schema_zip()
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    headers["Content-Disposition"] = 'attachment; filename="FundsXML.zip"'
    return Response(data, media_type="application/zip", headers=headers)
