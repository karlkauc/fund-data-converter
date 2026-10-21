"""Conversion orchestration shared by the HTTP API: detect the input, convert, report."""

from __future__ import annotations

import base64
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from app.config import settings
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml
from app.convert.to_tpt import extract_tpt
from app.ingest.fundsxml_reader import FundsXmlReadError, parse_fundsxml
from app.ingest.tpt_reader import TptReadError, read_tpt
from app.model.issues import Issue
from app.spec.catalog import load_catalog
from app.writers.tpt_writer import CSV_DELIMITERS, write_csv, write_xlsx

PREVIEW_ROWS = 200
PREVIEW_KEYS = ("1", "6", "12", "14", "17", "21", "22", "24", "26")
XML_PREVIEW_BYTES = 60_000


class InputError(ValueError):
    """The upload cannot be converted (unreadable, wrong kind, …)."""


class TooLargeError(InputError):
    """The upload is readable but has more positions than the service converts."""


@dataclass
class Request:
    data: bytes
    filename: str
    tpt_version: str | None = None  # TPT input: force V7/V8; FundsXML input: output version
    include_block: bool = True
    include_core: bool = True
    output_format: str = "xlsx"  # FundsXML → TPT: xlsx | csv
    delimiter: str = "semicolon"
    all_columns: bool = True


def detect_kind(data: bytes, filename: str) -> str:
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        return "fundsxml"
    if filename.lower().endswith(".xml"):
        return "fundsxml"
    return "tpt"


def run(req: Request) -> dict:
    kind = detect_kind(req.data, req.filename)
    return _tpt_to_fundsxml(req) if kind == "tpt" else _fundsxml_to_tpt(req)


def _tpt_to_fundsxml(req: Request) -> dict:
    try:
        doc = read_tpt(req.data, req.filename, req.tpt_version or None)
    except TptReadError as exc:
        raise InputError(str(exc)) from exc
    _check_size(len(doc.rows))
    result = convert_tpt_to_fundsxml(
        doc, ConvertOptions(include_block=req.include_block, include_core=req.include_core)
    )
    catalog = load_catalog(doc.version)
    portfolios = _portfolio_summary([r.values for r in doc.rows])
    name = f"{_stem(req.filename)}_FundsXML.xml"
    return {
        "direction": "tpt-to-fundsxml",
        "input": {
            "filename": req.filename,
            "kind": "tpt",
            "format": doc.file_format,
            "delimiter": doc.delimiter,
            "version": doc.version,
            "versionSource": doc.version_source,
            "columns": len(doc.columns),
            "unmappedColumns": doc.unmapped_headers,
        },
        "summary": {
            **{k: v for k, v in result.stats.items() if k != "coverage"},
            "portfolioList": portfolios,
        },
        "coverage": _coverage_summary(result.stats["coverage"], catalog),
        "issues": [i.to_dict() for i in result.issues],
        "validation": {"valid": result.valid, "errors": result.validation_errors},
        "preview": _preview([r.values for r in doc.rows], catalog),
        "xmlPreview": _xml_preview(result.xml),
        "xmlPreviewTruncated": len(result.xml) > XML_PREVIEW_BYTES,
        "output": _file(name, "application/xml", result.xml),
    }


def _fundsxml_to_tpt(req: Request) -> dict:
    try:
        root = parse_fundsxml(req.data)
    except FundsXmlReadError as exc:
        raise InputError(str(exc)) from exc
    _check_size(
        max(
            int(root.xpath("count(Funds/Fund/FundDynamicData/Portfolios/Portfolio/Positions/Position)")),
            int(
                root.xpath(
                    "count(Funds/Fund/SingleFund/ShareClasses/ShareClass/Portfolios/Portfolio/Positions/Position)"
                )
            ),
            int(root.xpath("count(RegulatoryReportings/IndirectReporting/*/Portfolio/Positions/Position)")),
        )
    )
    extract = extract_tpt(root, req.tpt_version or None)
    if not extract.rows:
        raise InputError("; ".join(i.message for i in extract.issues) or "no positions found")
    catalog = load_catalog(extract.version)
    stem = _stem(req.filename)
    if req.output_format == "csv":
        delim = CSV_DELIMITERS.get(req.delimiter, ";")
        data = write_csv(extract.rows, extract.version, delim, req.all_columns)
        out = _file(f"{stem}_TPT_{extract.version}.csv", "text/csv", data)
    else:
        data = write_xlsx(extract.rows, extract.version, req.all_columns)
        out = _file(
            f"{stem}_TPT_{extract.version}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data,
        )
    return {
        "direction": "fundsxml-to-tpt",
        "input": {
            "filename": req.filename,
            "kind": "fundsxml",
            "source": extract.source,
            "version": extract.version,
        },
        "summary": {**extract.stats, "portfolioList": _portfolio_summary(extract.rows)},
        "coverage": _coverage_from_rows(extract.rows, catalog),
        "issues": [i.to_dict() for i in extract.issues],
        "validation": None,
        "preview": _preview(extract.rows, catalog),
        "xmlPreview": None,
        "output": out,
    }


# ---------------------------------------------------------------------------


def _stem(filename: str) -> str:
    stem = PurePath(filename or "upload").stem
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] or "upload"


def _xml_preview(xml: bytes) -> str:
    """The start of the document, cut at a line end so no tag is split."""
    if len(xml) <= XML_PREVIEW_BYTES:
        return xml.decode("utf-8")
    head = xml[:XML_PREVIEW_BYTES]
    cut = head.rfind(b"\n")
    return head[: cut + 1 if cut > 0 else len(head)].decode("utf-8", errors="ignore")


def _check_size(positions: int) -> None:
    if positions > settings.max_positions:
        raise TooLargeError(
            f"the file has {positions} positions; this service converts up to {settings.max_positions} "
            "per file – split it by portfolio"
        )


def _file(name: str, mime: str, data: bytes) -> dict:
    zipped = len(data) > settings.zip_threshold_mb * 1024 * 1024
    if zipped:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr(name, data)
        data, name, mime = buf.getvalue(), name + ".zip", "application/zip"
    return {
        "filename": name,
        "mimeType": mime,
        "size": len(data),
        "zipped": zipped,
        "base64": base64.b64encode(data).decode("ascii"),
    }


def _portfolio_summary(rows: list[dict[str, str]]) -> list[dict]:
    seen: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.get("1", ""), r.get("6", ""))
        entry = seen.setdefault(
            key,
            {
                "id": key[0],
                "date": key[1],
                "name": r.get("3", ""),
                "currency": r.get("4", ""),
                "nav": r.get("5", ""),
                "positions": 0,
            },
        )
        entry["positions"] += 1
    return list(seen.values())


def _preview(rows: list[dict[str, str]], catalog) -> dict:
    keys = [k for k in PREVIEW_KEYS if k in catalog.by_key]
    return {
        "columns": [{"key": k, "name": catalog.by_key[k].num_data} for k in keys],
        "rows": [[r.get(k, "") for k in keys] for r in rows[:PREVIEW_ROWS]],
        "total": len(rows),
    }


def _coverage_summary(coverage: dict[str, dict[str, bool]], catalog) -> dict:
    fields = []
    for f in catalog.fields:
        c = coverage.get(f.num_key)
        if c is None:
            continue
        fields.append({"key": f.num_key, "name": f.num_data, **c})
    extra = [k for k in coverage if k not in catalog.by_key]
    for k in extra:
        fields.append({"key": k, "name": k, **coverage[k]})
    return {
        "present": len(fields),
        "block": sum(1 for f in fields if f["block"]),
        "core": sum(1 for f in fields if f["core"]),
        "custom": sum(1 for f in fields if f["custom"]),
        "fields": fields,
    }


def _coverage_from_rows(rows: list[dict[str, str]], catalog) -> dict:
    present = {k for r in rows for k in r if r[k]}
    fields = [
        {"key": f.num_key, "name": f.num_data, "block": False, "core": False, "custom": False}
        for f in catalog.fields
        if f.num_key in present
    ]
    return {
        "present": len(fields),
        "block": 0,
        "core": 0,
        "custom": 0,
        "fields": fields,
        "total": len(catalog.fields),
    }


def issue_dict(level: str, code: str, message: str) -> dict:
    return Issue(level, code, message).to_dict()
