"""POST /api/convert – one stateless request: upload, convert, report + file."""

from __future__ import annotations

import logging
import time
from pathlib import PurePath

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.config import settings
from app.rate_limit import limiter
from app.service import InputError, TooLargeError, detect_kind, run
from app.service import Request as ConvertRequest
from app.usage.context import emit
from app.usage.conversion import conversion_fields, is_sample

logger = logging.getLogger(__name__)
router = APIRouter()

# CPU-bound work runs in worker threads; this caps how many run at once per instance.
_slots = anyio.CapacityLimiter(settings.max_concurrent_conversions)


# Upload extension -> usage ``source`` (what a successful conversion reports as the input format).
_SOURCE_BY_SUFFIX = {".xlsx": "xlsx", ".xls": "xlsx", ".csv": "csv", ".xml": "xml"}


def _input_source(data: bytes, filename: str) -> str | None:
    """``source`` of a conversion that failed: a bundled example, else the file extension."""
    if data and is_sample(data):
        return "sample"
    source = _SOURCE_BY_SUFFIX.get(PurePath(filename).suffix.lower())
    if source is None and data and detect_kind(data, filename) == "fundsxml":
        return "xml"
    return source


def _direction(data: bytes, filename: str) -> str | None:
    """The direction ``run`` would take, or None when neither content nor name tell."""
    suffix = PurePath(filename).suffix.lower()
    if not data and suffix not in _SOURCE_BY_SUFFIX:
        return None
    return "tpt-to-fundsxml" if detect_kind(data, filename) == "tpt" else "fundsxml-to-tpt"


def _reject(
    status_code: int, detail: str, reason: str, data: bytes, filename: str, tpt_version: str | None
) -> HTTPException:
    """Record a request the handler turns away and build its HTTPException.

    ``reason`` is a fixed code for ``error_detail`` (never the message, as for
    failed conversions). Returned, not raised, so call sites read ``raise _reject(...)``.
    """
    emit(
        "convert",
        status="rejected",
        status_code=status_code,
        error_detail=reason,
        direction=_direction(data, filename),
        source=_input_source(data, filename),
        tpt_version=tpt_version,
        input_bytes=len(data),
    )
    return HTTPException(status_code, detail)


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
    filename = file.filename or "upload"
    version = (tpt_version or "").upper() or None
    # An unknown version is not recorded: tpt_version holds V7/V8 only.
    requested = version if version in ("V7", "V8") else None
    if len(data) > settings.max_upload_bytes:
        detail = f"file exceeds the {settings.max_upload_mb} MB limit"
        raise _reject(413, detail, "too_large", data, filename, requested)
    if not data:
        raise _reject(400, "the uploaded file is empty", "empty_file", data, filename, requested)
    if version not in (None, "V7", "V8"):
        raise _reject(400, "tpt_version must be V7 or V8", "bad_tpt_version", data, filename, None)
    req = ConvertRequest(
        data=data,
        filename=filename,
        tpt_version=version,
        include_block=_flag(include_block, True),
        include_core=_flag(include_core, True),
        output_format=(output_format or "xlsx").lower(),
        delimiter=(delimiter or "semicolon").lower(),
        all_columns=_flag(all_columns, True),
    )
    if not (req.include_block or req.include_core):
        detail = "select the TPT block, the core structures or both"
        raise _reject(400, detail, "nothing_selected", data, filename, version)
    start = time.perf_counter()
    try:
        result = await anyio.to_thread.run_sync(run, req, limiter=_slots)
    except InputError as exc:
        # Only the exception class: messages may quote values from the file.
        emit(
            "convert",
            status="rejected" if isinstance(exc, TooLargeError) else "parse_error",
            status_code=422,
            error_detail=type(exc.__cause__ or exc).__name__,
            direction=_direction(data, req.filename),
            source=_input_source(data, req.filename),
            tpt_version=version,
            input_bytes=len(data),
            duration_ms=_elapsed_ms(start),
        )
        raise HTTPException(422, str(exc)) from exc
    emit(
        "convert",
        status="ok",
        status_code=200,
        duration_ms=_elapsed_ms(start),
        **conversion_fields(req, result),
    )
    return result


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
