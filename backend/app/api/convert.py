"""POST /api/convert – one stateless request: upload, convert, report + file.

The browser takes the JSON report with the file embedded as base64. Scripts can ask
for the bare file (key figures in ``X-Conversion-*`` headers) or a zip of file,
``report.json`` and ``issues.csv`` instead (``response=file|zip``; see /api-docs).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import time
import zipfile
from pathlib import PurePath

import anyio
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.rate_limit import limiter
from app.service import DIRECTIONS, InputError, OutputFile, TooLargeError, detect_kind
from app.service import Request as ConvertRequest
from app.service import convert as convert_request
from app.usage.context import emit
from app.usage.conversion import conversion_fields, is_sample

logger = logging.getLogger(__name__)
router = APIRouter()

# CPU-bound work runs in worker threads; this caps how many run at once per instance.
_slots = anyio.CapacityLimiter(settings.max_concurrent_conversions)

RESPONSE_MODES = ("json", "file", "zip")
ISSUE_CSV_COLUMNS = ("level", "code", "field", "row", "path", "value", "message")
REPORT_HEADERS = (
    "X-Conversion-Direction",
    "X-Conversion-Valid",
    "X-Conversion-Portfolios",
    "X-Conversion-Positions",
    "X-Conversion-Errors",
    "X-Conversion-Warnings",
    "X-Conversion-Infos",
    "X-Conversion-Data-Lost",
    "X-Conversion-Issue-Codes",
    "X-Conversion-Report",
)

DESCRIPTION = """Converts a TPT file (XLSX or CSV, V7 or V8) to FundsXML 4, or a FundsXML 4 document
to TPT. The direction follows from the upload; pass `direction` to have a mismatch refused.

`response` picks the answer:

- `json` (default): the report, with the converted file base64-encoded in `output.base64`.
- `file`: the converted file itself; key figures in `X-Conversion-*` headers and the compact
  report as base64url JSON in `X-Conversion-Report`.
- `zip`: the converted file, `report.json` and `issues.csv` in one zip.

Errors are `{"detail": "…"}` with status 400 (bad option), 413 (too large), 422 (not
convertible) or 429 (rate limit, see `Retry-After`). Documentation: /api-docs."""


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


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.post(
    "/convert",
    tags=["convert"],
    summary="Convert TPT ⇄ FundsXML",
    response_model=None,
    description=DESCRIPTION,
    responses={
        200: {
            "description": "The report (json), the converted file (file) or a zip of both (zip).",
            "content": {"application/json": {}, "application/octet-stream": {}, "application/zip": {}},
        },
        400: {"description": "Invalid option"},
        413: {"description": "Upload above the size limit"},
        422: {"description": "The file cannot be converted"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(settings.convert_rate_limit)
async def convert(
    request: Request,
    file: UploadFile = File(..., description="TPT (.xlsx, .csv) or FundsXML 4 (.xml)"),
    tpt_version: str | None = Form(
        None, description="V7 or V8. TPT input: overrides the detected version; FundsXML input: TPT version"
    ),
    include_block: str | None = Form(None, description="TPT → FundsXML: write the TPT block (default true)"),
    include_core: str | None = Form(None, description="TPT → FundsXML: write core structures (default true)"),
    output_format: str | None = Form(None, description="FundsXML → TPT: xlsx (default) or csv"),
    delimiter: str | None = Form(None, description="CSV output: semicolon (default), comma, pipe or tab"),
    all_columns: str | None = Form(None, description="FundsXML → TPT: write every TPT column (default true)"),
    response: str | None = Form(None, description="json (default), file or zip"),
    direction: str | None = Form(
        None, description="auto (default), tpt-to-fundsxml or fundsxml-to-tpt; a mismatch is refused with 422"
    ),
    preview: str | None = Form(None, description="json: include the table and XML previews (default true)"),
    data_supplier_name: str | None = Form(
        None, description="TPT → FundsXML: ControlData/DataSupplier/Name (default: TPT field 117)"
    ),
    data_supplier_short: str | None = Form(None, description="TPT → FundsXML: DataSupplier/Short"),
    data_supplier_country: str | None = Form(
        None, description="TPT → FundsXML: DataSupplier/SystemCountry, ISO 3166 alpha-2 (default: field 122)"
    ),
) -> Response | dict:
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
    mode = (response or "json").lower()
    if mode not in RESPONSE_MODES:
        raise _reject(400, "response must be json, file or zip", "bad_response", data, filename, requested)
    wanted = (direction or "auto").lower()
    if wanted not in ("auto", *DIRECTIONS):
        detail = "direction must be auto, tpt-to-fundsxml or fundsxml-to-tpt"
        raise _reject(400, detail, "bad_direction", data, filename, requested)
    req = ConvertRequest(
        data=data,
        filename=filename,
        tpt_version=version,
        include_block=_flag(include_block, True),
        include_core=_flag(include_core, True),
        output_format=(output_format or "xlsx").lower(),
        delimiter=(delimiter or "semicolon").lower(),
        all_columns=_flag(all_columns, True),
        direction=wanted,
        preview=_flag(preview, True),
        data_supplier_name=_text(data_supplier_name),
        data_supplier_short=_text(data_supplier_short),
        data_supplier_country=_text(data_supplier_country),
    )
    if not (req.include_block or req.include_core):
        detail = "select the TPT block, the core structures or both"
        raise _reject(400, detail, "nothing_selected", data, filename, version)
    start = time.perf_counter()
    try:
        report, out = await anyio.to_thread.run_sync(convert_request, req, limiter=_slots)
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
            response_mode=mode,
        )
        raise HTTPException(422, str(exc)) from exc
    report["meta"]["durationMs"] = _elapsed_ms(start)
    emit(
        "convert",
        status="ok",
        status_code=200,
        duration_ms=report["meta"]["durationMs"],
        response_mode=mode,
        **conversion_fields(req, report),
    )
    if mode == "file":
        return _file_response(report, out)
    if mode == "zip":
        return _zip_response(report, out)
    report["output"]["base64"] = base64.b64encode(out.data).decode("ascii")
    return report


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _file_response(report: dict, out: OutputFile) -> Response:
    summary = report["summary"]
    counts = report["issueCounts"]
    valid = (report["validation"] or {}).get("valid")
    loss = report["dataLoss"]
    compact = json.dumps(_compact(report), ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Disposition": f'attachment; filename="{out.filename}"',
        "X-Conversion-Direction": report["direction"],
        "X-Conversion-Valid": "" if valid is None else str(valid).lower(),
        "X-Conversion-Portfolios": str(summary.get("portfolios", "")),
        "X-Conversion-Positions": str(summary.get("positions", "")),
        "X-Conversion-Errors": str(counts["error"]),
        "X-Conversion-Warnings": str(counts["warning"]),
        "X-Conversion-Infos": str(counts["info"]),
        "X-Conversion-Data-Lost": "" if loss is None else str(loss["lost"]),
        "X-Conversion-Issue-Codes": ",".join(_issue_codes(report)),
        "X-Conversion-Report": base64.urlsafe_b64encode(compact.encode()).decode("ascii"),
        "Access-Control-Expose-Headers": ", ".join(("Content-Disposition", *REPORT_HEADERS)),
    }
    return Response(out.data, media_type=out.mime, headers=headers)


def _zip_response(report: dict, out: OutputFile) -> Response:
    name, data = out.filename, out.data
    if out.zipped:  # one zip is enough: put the file itself into the bundle
        with zipfile.ZipFile(io.BytesIO(out.data)) as inner:
            name = inner.namelist()[0]
            data = inner.read(name)
    full = {k: v for k, v in report.items() if k not in ("preview", "xmlPreview", "xmlPreviewTruncated")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(name, data)
        zf.writestr("report.json", json.dumps(full, ensure_ascii=False, indent=2))
        zf.writestr("issues.csv", _issues_csv(report["issues"]))
    bundle = f"{PurePath(name).stem}_conversion.zip"
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{bundle}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


def _issues_csv(issues: list[dict]) -> bytes:
    """Semicolon-separated with a BOM, so Excel opens it with umlauts intact."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(ISSUE_CSV_COLUMNS)
    for issue in issues:
        writer.writerow([issue.get(c, "") for c in ISSUE_CSV_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")


def _issue_codes(report: dict) -> list[str]:
    return sorted({i["code"] for i in report["issues"]})


def _compact(report: dict) -> dict:
    """The report without per-row lists, small enough for a response header."""
    validation = report["validation"]
    return {
        "direction": report["direction"],
        "input": {k: v for k, v in report["input"].items() if k != "unmappedColumns"},
        "summary": {k: v for k, v in report["summary"].items() if k != "portfolioList"},
        "coverage": {k: v for k, v in report["coverage"].items() if k != "fields"},
        "validation": None
        if validation is None
        else {"valid": validation["valid"], "errors": len(validation["errors"])},
        "issueCounts": report["issueCounts"],
        "issueCodes": _issue_codes(report),
        "dataLoss": report["dataLoss"],
        "output": report["output"],
        "meta": report["meta"],
    }
