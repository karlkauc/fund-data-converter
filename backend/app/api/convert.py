"""POST /api/convert – one stateless request: upload, convert, report + file."""

from __future__ import annotations

import logging

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.rate_limit import limiter
from app.service import InputError, run
from app.service import Request as ConvertRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# CPU-bound work runs in worker threads; this caps how many run at once per instance.
_slots = anyio.CapacityLimiter(settings.max_concurrent_conversions)


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")


@router.post("/convert")
@limiter.limit(settings.convert_rate_limit)
async def convert(
    request: Request,
    file: UploadFile = File(...),
    tpt_version: str | None = Form(None),
    include_block: str | None = Form(None),
    include_core: str | None = Form(None),
    output_format: str | None = Form(None),
    delimiter: str | None = Form(None),
    all_columns: str | None = Form(None),
) -> dict:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"file exceeds the {settings.max_upload_mb} MB limit")
    if not data:
        raise HTTPException(400, "the uploaded file is empty")
    version = (tpt_version or "").upper() or None
    if version not in (None, "V7", "V8"):
        raise HTTPException(400, "tpt_version must be V7 or V8")
    req = ConvertRequest(
        data=data,
        filename=file.filename or "upload",
        tpt_version=version,
        include_block=_flag(include_block, True),
        include_core=_flag(include_core, True),
        output_format=(output_format or "xlsx").lower(),
        delimiter=(delimiter or "semicolon").lower(),
        all_columns=_flag(all_columns, True),
    )
    if not (req.include_block or req.include_core):
        raise HTTPException(400, "select the TPT block, the core structures or both")
    try:
        return await anyio.to_thread.run_sync(run, req, limiter=_slots)
    except InputError as exc:
        raise HTTPException(422, str(exc)) from exc
