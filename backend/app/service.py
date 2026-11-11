"""Conversion orchestration shared by the HTTP API: detect the input, convert, report."""

from __future__ import annotations

import base64
import gc
import hashlib
import io
import re
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePath

from app import __version__
from app.config import settings
from app.convert.fundsxml_to_openfunds import OfExtract, extract_openfunds
from app.convert.hub import not_carried_to_tpt, tpt_fields_without_column
from app.convert.openfunds_to_fundsxml import OfConvertOptions, convert_openfunds_to_fundsxml
from app.convert.to_fundsxml import TPT_BLOCK, ConversionResult, ConvertOptions, convert_tpt_to_fundsxml
from app.convert.to_tpt import TptExtract, extract_tpt
from app.ingest.fundsxml_reader import FundsXmlReadError, parse_fundsxml
from app.ingest.limits import TooManyRowsError, check_xlsx_rows
from app.ingest.openfunds_reader import OfDocument, OpenfundsReadError, looks_like_openfunds, read_openfunds
from app.ingest.tpt_reader import TptDocument, TptReadError, pick_sheet, read_tpt
from app.mapping.openfunds_templates import templates
from app.mapping.transforms import cic_category
from app.model.issues import Issue
from app.schema.model import fundsxml_version
from app.spec.catalog import load_catalog
from app.spec.openfunds import load_openfunds
from app.writers.openfunds_writer import write_openfunds
from app.writers.provenance import Provenance, with_xml_comment
from app.writers.tpt_writer import CSV_DELIMITERS, write_csv, write_xlsx

CIC_CATEGORIES = frozenset("1234567890ABCDEF")
OF_CIC = "OFPH000215"  # holding CIC column

PREVIEW_ROWS = 200
PREVIEW_KEYS = ("1", "6", "12", "14", "17", "21", "22", "24", "26")
OF_PREVIEW_KEYS = ("OFST020000", "OFST020060", "OFST020540", "OFDY000036", "OFDY000035", "OFDY000070")
XML_PREVIEW_BYTES = 60_000
# Start and end tags of a FundsXML within the upload limit are about a million.
MAX_XML_TAGS = 2_000_000
FORMATS = ("fundsxml", "tpt", "openfunds")
DIRECTIONS = tuple(f"{a}-to-{b}" for a in FORMATS for b in FORMATS if a != b)
# Target when the request names none: the first two keep the behaviour of the TPT ⇄ FundsXML-only
# first version of the converter.
DEFAULT_TARGET = {"tpt": "fundsxml", "fundsxml": "tpt", "openfunds": "fundsxml"}
KIND_TEXT = {"tpt": "a TPT file", "fundsxml": "a FundsXML document", "openfunds": "an openfunds file"}


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
    all_columns: bool | None = None  # every column: TPT output by default, openfunds output on request
    direction: str = "auto"  # auto | one of DIRECTIONS (refused when the upload is another format)
    target: str | None = None  # with direction auto: tpt | fundsxml | openfunds (default DEFAULT_TARGET)
    of_header_names: bool = False  # openfunds output: second header row with the field names
    non_openfunds_columns: bool = True  # TPT → openfunds: TPT fields without a column as TPT_<field>
    # openfunds → FundsXML: TPT values the FundsXML implies as TPT_<field> attributes too
    implied_tpt_attributes: bool = True
    preview: bool = True  # False drops the table and XML previews (API callers rarely want them)
    data_supplier_name: str | None = None  # TPT → FundsXML: ControlData/DataSupplier overrides
    data_supplier_short: str | None = None
    data_supplier_country: str | None = None
    # Set while reading the upload ("TPT V7", "openfunds", "FundsXML"): named in the output's metadata.
    source_format: str = ""
    # Set while reading and converting: counts and classes for the usage statistics
    # (app.usage.conversion), never values from the file.
    telemetry: dict = field(default_factory=dict)


@dataclass
class OutputFile:
    """The converted file as delivered: zipped above ``ZIP_THRESHOLD_MB``."""

    data: bytes
    filename: str
    mime: str
    zipped: bool = False


def detect_kind(data: bytes, filename: str) -> str:
    if _is_fundsxml(data, filename):
        return "fundsxml"
    if looks_like_openfunds(data, filename):
        return "openfunds"
    return "tpt"


def _is_fundsxml(data: bytes, filename: str) -> bool:
    return data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<") or filename.lower().endswith(".xml")


def resolve_direction(req: Request, kind: str) -> str:
    """The direction for an upload of ``kind``; InputError if the request asks for another one."""
    if req.direction != "auto":
        source, _, target = req.direction.partition("-to-")
        if source != kind:
            raise InputError(f"direction is {req.direction}, but the upload is {KIND_TEXT[kind]}")
    else:
        # The browser cannot tell a TPT from an openfunds XLSX; a target equal to the format of the
        # upload means "the other format", i.e. the default target.
        target = (req.target or "").lower()
        if not target or target == kind:
            target = DEFAULT_TARGET[kind]
    if target not in FORMATS or target == kind:
        raise InputError(f"the upload is {KIND_TEXT[kind]}; target must be one of the other formats")
    return f"{kind}-to-{target}"


def run(req: Request) -> dict:
    """The report with the converted file embedded as base64 (the browser's format)."""
    report, out = convert(req)
    report["output"]["base64"] = base64.b64encode(out.data).decode("ascii")
    return report


_gc_lock = threading.Lock()
_gc_users = 0
_gc_was_enabled = False


@contextmanager
def _cyclic_gc_paused() -> Iterator[None]:
    """Pause Python's cycle collector while conversions run.

    A conversion builds millions of small objects (tree nodes, elements, records) that live until
    it ends and form no reference cycles. Each full collection walks all of them, which cost about
    a fifth of the time of a large file on Python 3.12. Reference counting still frees everything
    as usual; the collector resumes when the last running conversion ends.
    """
    global _gc_users, _gc_was_enabled
    with _gc_lock:
        if _gc_users == 0:
            _gc_was_enabled = gc.isenabled()
            gc.disable()
        _gc_users += 1
    try:
        yield
    finally:
        with _gc_lock:
            _gc_users -= 1
            if _gc_users == 0 and _gc_was_enabled:
                gc.enable()


def convert(req: Request) -> tuple[dict, OutputFile]:
    """The report (``output`` holds metadata only) and the converted file."""
    with _cyclic_gc_paused():
        return _convert(req)


def _convert(req: Request) -> tuple[dict, OutputFile]:
    _refuse_large_xlsx(req)
    direction = resolve_direction(req, detect_kind(req.data, req.filename))
    report, out, loss = HANDLERS[direction](req)
    report["output"] = {
        "filename": out.filename,
        "mimeType": out.mime,
        "size": len(out.data),
        "zipped": out.zipped,
        "sha256": hashlib.sha256(out.data).hexdigest(),
    }
    issues = report["issues"]
    report["issueCounts"] = {
        level: sum(1 for i in issues if i["level"] == level) for level in ("error", "warning", "info")
    }
    report["dataLoss"] = loss
    report["meta"] = {
        "converterVersion": __version__,
        "fundsxmlSchema": fundsxml_version(),
        "input": {"bytes": len(req.data), "sha256": hashlib.sha256(req.data).hexdigest()},
    }
    if not req.preview:
        for key in ("preview", "xmlPreview", "xmlPreviewTruncated"):
            report.pop(key, None)
    return report, out


def _refuse_large_xlsx(req: Request) -> None:
    """Refuse a TPT or openfunds XLSX with too many rows before reading it at all.

    Telling TPT from openfunds reads the workbook, which for a large sheet without a stored
    dimension costs as much as reading it. Whichever it is, the reader refuses the file if its
    TPT sheet has too many rows (openfunds reads every sheet), so that is checked first – when
    nothing else could refuse the request sooner (a direction or target that does not fit).
    """
    target = (req.target or "").lower()
    if req.direction != "auto" or (target and target not in FORMATS) or _is_fundsxml(req.data, req.filename):
        return
    try:
        check_xlsx_rows(req.data, pick_sheet)
    except TooManyRowsError as exc:
        raise _too_large(exc) from exc


def _data_loss(issues: list[dict], totals: dict[str, int]) -> dict:
    """TPT values FundsXML did not take where they belong, counted before the 25-per-code cap.

    ``block_value_rejected`` is an error (lost) without core structures and a warning (kept as a
    custom attribute) with them; ``core_value_rejected`` always falls back to a custom attribute;
    ``core_value_skipped`` values are still in the TPT block.
    """
    block_level = next((i["level"] for i in issues if i["code"] == "block_value_rejected"), None)
    block = totals.get("block_value_rejected", 0)
    lost = block if block_level == "error" else 0
    return {
        "lost": lost,
        "keptAsCustomAttribute": block - lost + totals.get("core_value_rejected", 0),
        "notInCoreStructures": totals.get("core_value_skipped", 0),
        "codes": sorted(
            c for c in ("block_value_rejected", "core_value_rejected", "core_value_skipped") if totals.get(c)
        ),
    }


# -- reading -----------------------------------------------------------------------


def _read_tpt(req: Request) -> TptDocument:
    try:
        doc = read_tpt(req.data, req.filename, req.tpt_version or None)
    except TooManyRowsError as exc:
        raise _too_large(exc) from exc
    except TptReadError as exc:
        raise InputError(str(exc)) from exc
    _check_size(len(doc.rows))
    req.source_format = f"TPT {doc.version}"
    req.telemetry |= {
        "cic_categories": cic_categories(r.values.get("12") for r in doc.rows),
        # Turned into countries, months and keyed fingerprints by app.usage.conversion, never stored as is.
        "isins": sorted({r.values.get("1", "") for r in doc.rows}),
        "nav_dates": sorted({r.values.get("6", "") for r in doc.rows}),
    }
    return doc


def _read_openfunds(req: Request) -> OfDocument:
    try:
        doc = read_openfunds(req.data, req.filename)
    except TooManyRowsError as exc:
        raise _too_large(exc) from exc
    except OpenfundsReadError as exc:
        raise InputError(str(exc)) from exc
    _check_size(len(doc.holdings))
    req.source_format = "openfunds"
    req.telemetry |= {
        "of_layout": doc.layout,
        "of_templates": openfunds_templates_used(r.values for r in doc.shareclasses),
        "shareclass_count": len(doc.shareclasses),
        "holding_count": len(doc.holdings),
        "cic_categories": cic_categories(h.values.get(OF_CIC) for h in doc.holdings),
        "isins": sorted({r.values.get("OFST020000", "") for r in doc.shareclasses}),
        "nav_dates": sorted(
            {h.values.get("OFPH000010", "") for h in doc.holdings}
            or {r.values.get(k, "") for r in doc.shareclasses for k in ("OFDY000071", "OFDY000036")}
        ),
    }
    return doc


def _parse_fundsxml(req: Request):
    # A tree costs about 130 bytes per element; real documents spend ~26 bytes of text on a tag,
    # a crafted one 4 ("<a/>"). Refused before parsing, so 25 MB cannot become gigabytes.
    if req.data.count(b"<") > MAX_XML_TAGS:
        raise TooLargeError(
            f"the document has more than {MAX_XML_TAGS} tags; this service converts up to "
            f"{settings.max_positions} positions per file – split it by portfolio"
        )
    try:
        root = parse_fundsxml(req.data)
    except FundsXmlReadError as exc:
        raise InputError(str(exc)) from exc
    _check_fundsxml_size(root)
    req.source_format = "FundsXML"
    req.telemetry |= {
        "has_tpt_block": root.find("/".join(TPT_BLOCK)) is not None,
        "shareclass_count": int(root.xpath("count(Funds/Fund/SingleFund/ShareClasses/ShareClass)")),
        "asset_count": int(root.xpath("count(AssetMasterData/Asset)")),
        "cic_categories": cic_categories(
            root.xpath("AssetMasterData/Asset/Classifications/Classification[ListedGroup='CIC']/Value/text()")
        ),
        "isins": sorted(
            set(root.xpath("Funds/Fund/SingleFund/ShareClasses/ShareClass/Identifiers/ISIN/text()"))
        ),
        "nav_dates": sorted(
            set(root.xpath("Funds/Fund//Portfolios/Portfolio/NavDate/text()"))
            or set(root.xpath("Funds/Fund//TotalAssetValues/TotalAssetValue/NavDate/text()"))
        ),
    }
    return root


def _provenance(req: Request, target_format: str, contents: str = "") -> Provenance:
    return Provenance(req.filename, req.source_format or "upload", target_format, contents)


def _contents(stats: dict) -> str:
    """ "2 share classes, 120 positions" from a conversion's stats."""
    labels = (("funds", "fund", "funds"), ("shareclasses", "share class", "share classes"))
    labels += (("portfolios", "portfolio", "portfolios"), ("positions", "position", "positions"))
    parts = [f"{stats[k]} {one if stats[k] == 1 else many}" for k, one, many in labels if k in stats]
    return ", ".join(parts)


def _with_comment(req: Request, xml: bytes, stats: dict) -> bytes:
    return with_xml_comment(xml, _provenance(req, f"FundsXML {fundsxml_version()}", _contents(stats)))


def _tpt_input(req: Request, doc: TptDocument) -> dict:
    return {
        "filename": req.filename,
        "kind": "tpt",
        "format": doc.file_format,
        "delimiter": doc.delimiter,
        "version": doc.version,
        "versionSource": doc.version_source,
        "columns": len(doc.columns),
        "unmappedColumns": doc.unmapped_headers,
    }


def _openfunds_input(req: Request, doc: OfDocument) -> dict:
    return {
        "filename": req.filename,
        "kind": "openfunds",
        "format": doc.file_format,
        "delimiter": doc.delimiter,
        "version": load_openfunds().version,
        "layout": doc.layout,
        "columns": len(doc.columns),
        "unmappedColumns": doc.extra_columns,
    }


def _tpt_options(req: Request) -> ConvertOptions:
    return ConvertOptions(
        include_block=req.include_block,
        include_core=req.include_core,
        data_supplier_name=req.data_supplier_name,
        data_supplier_short=req.data_supplier_short,
        data_supplier_country=req.data_supplier_country,
    )


def _of_options(req: Request) -> OfConvertOptions:
    return OfConvertOptions(
        data_supplier_name=req.data_supplier_name,
        data_supplier_short=req.data_supplier_short,
        data_supplier_country=req.data_supplier_country,
        implied_tpt_attributes=req.implied_tpt_attributes,
    )


# -- writing -----------------------------------------------------------------------


def _write_tpt(req: Request, extract: TptExtract) -> OutputFile:
    stem = _stem(req.filename)
    if req.output_format == "csv":
        delim = CSV_DELIMITERS.get(req.delimiter, ";")
        data = write_csv(extract.rows, extract.version, delim, req.all_columns is not False)
        return _package(f"{stem}_TPT_{extract.version}.csv", "text/csv", data)
    meta = _provenance(req, f"TPT {extract.version}", f"{len(extract.rows)} positions")
    data = write_xlsx(extract.rows, extract.version, req.all_columns is not False, meta)
    return _package(
        f"{stem}_TPT_{extract.version}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data,
    )


def _write_openfunds(req: Request, extract: OfExtract) -> OutputFile:
    if not extract.shareclasses and not extract.holdings:
        raise InputError("; ".join(i.message for i in extract.issues) or "no share classes found")
    data, name, mime = write_openfunds(
        extract.shareclasses,
        extract.holdings,
        "csv" if req.output_format == "csv" else "xlsx",
        CSV_DELIMITERS.get(req.delimiter, ";"),
        header_names=req.of_header_names,
        all_columns=bool(req.all_columns),
        stem=_stem(req.filename),
        meta=_provenance(
            req,
            f"openfunds {load_openfunds().version}",
            f"{len(extract.shareclasses)} share classes, {len(extract.holdings)} holdings",
        ),
    )
    return _package(name, mime, data)


def _extract_tpt(root, version: str | None) -> TptExtract:
    extract = extract_tpt(root, version)
    if not extract.rows:
        raise InputError("; ".join(i.message for i in extract.issues) or "no positions found")
    return extract


def cic_categories(cics) -> list[str]:
    """The CIC categories (3rd character: 1 government bonds … 7 cash, A–F derivatives) present."""
    return sorted({c for cic in cics if cic and (c := cic_category(cic)) in CIC_CATEGORIES})


def openfunds_templates_used(records) -> list[str]:
    """The FinDatEx templates (EMT, EPT, EET, EFT) with at least one filled field in the share classes."""
    filled = {k for r in records for k, v in r.items() if v}
    return sorted({tpl.name for tpl in templates() for f in tpl.fields if f.of_id in filled})


# -- the six directions -------------------------------------------------------------


def _tpt_to_fundsxml(req: Request):
    doc = _read_tpt(req)
    result = convert_tpt_to_fundsxml(doc, _tpt_options(req))
    result.xml = _with_comment(req, result.xml, result.stats)
    catalog = load_catalog(doc.version)
    report = {
        "direction": "tpt-to-fundsxml",
        "input": _tpt_input(req, doc),
        "summary": {
            **{k: v for k, v in result.stats.items() if k != "coverage"},
            "portfolioList": _portfolio_summary([r.values for r in doc.rows]),
        },
        "coverage": _coverage_summary(result.stats["coverage"], catalog),
        "issues": [i.to_dict() for i in result.issues],
        "validation": {"valid": result.valid, "errors": result.validation_errors},
        "preview": _preview([r.values for r in doc.rows], catalog),
        **_xml_report(result.xml),
    }
    out = _package(f"{_stem(req.filename)}_FundsXML.xml", "application/xml", result.xml)
    return report, out, _data_loss(report["issues"], result.issue_totals)


def _openfunds_to_fundsxml(req: Request):
    doc = _read_openfunds(req)
    result = convert_openfunds_to_fundsxml(doc, _of_options(req))
    result.xml = _with_comment(req, result.xml, result.stats)
    report = {
        "direction": "openfunds-to-fundsxml",
        "input": _openfunds_input(req, doc),
        "summary": {
            **{k: v for k, v in result.stats.items() if k != "coverage"},
            "portfolioList": _shareclass_summary(
                [r.values for r in doc.shareclasses], [h.values for h in doc.holdings]
            ),
        },
        "coverage": _of_coverage(result.stats["coverage"]),
        "issues": [i.to_dict() for i in result.issues],
        "validation": {"valid": result.valid, "errors": result.validation_errors},
        "preview": _of_preview([r.values for r in doc.shareclasses]),
        **_xml_report(result.xml),
    }
    out = _package(f"{_stem(req.filename)}_FundsXML.xml", "application/xml", result.xml)
    return report, out, _of_data_loss(result)


def _fundsxml_to_tpt(req: Request):
    root = _parse_fundsxml(req)
    extract = _extract_tpt(root, req.tpt_version or None)
    report = _tpt_output_report(
        req, "fundsxml-to-tpt", {"filename": req.filename, "kind": "fundsxml"}, extract
    )
    return report, _write_tpt(req, extract), _version_loss(extract)


def _fundsxml_to_openfunds(req: Request):
    root = _parse_fundsxml(req)
    extract = extract_openfunds(root, req.non_openfunds_columns)
    out = _write_openfunds(req, extract)
    report = _of_output_report(
        "fundsxml-to-openfunds", {"filename": req.filename, "kind": "fundsxml"}, extract
    )
    return report, out, None


def _tpt_to_openfunds(req: Request):
    doc = _read_tpt(req)
    hop = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=True, include_core=True, validate=False))
    extract = extract_openfunds(parse_fundsxml(hop.xml), req.non_openfunds_columns)
    out = _write_openfunds(req, extract)
    report = _of_output_report("tpt-to-openfunds", _tpt_input(req, doc), extract, _hop_issues(hop))
    lost = [] if req.non_openfunds_columns else tpt_fields_without_column([r.values for r in doc.rows])
    catalog = load_catalog(doc.version)
    names = [catalog.by_key[k].num_data if k in catalog.by_key else k for k in lost]
    report["issues"] += _not_carried("TPT", "openfunds", names)
    return report, out, _hop_loss(names)


def _openfunds_to_tpt(req: Request):
    doc = _read_openfunds(req)
    hop = convert_openfunds_to_fundsxml(doc, OfConvertOptions(validate=False))
    extract = _extract_tpt(parse_fundsxml(hop.xml), req.tpt_version or None)
    report = _tpt_output_report(req, "openfunds-to-tpt", _openfunds_input(req, doc), extract)
    report["issues"] = _hop_issues(hop) + report["issues"]
    extra = [h for r in doc.shareclasses + doc.holdings for h in r.extra]
    lost = not_carried_to_tpt([r.values for r in doc.shareclasses], [r.values for r in doc.holdings], extra)
    report["issues"] += _not_carried("openfunds", "TPT", lost)
    return report, _write_tpt(req, extract), _hop_loss(lost, extract)


HANDLERS = {
    "tpt-to-fundsxml": _tpt_to_fundsxml,
    "fundsxml-to-tpt": _fundsxml_to_tpt,
    "openfunds-to-fundsxml": _openfunds_to_fundsxml,
    "fundsxml-to-openfunds": _fundsxml_to_openfunds,
    "tpt-to-openfunds": _tpt_to_openfunds,
    "openfunds-to-tpt": _openfunds_to_tpt,
}


# -- reports -----------------------------------------------------------------------


def _xml_report(xml: bytes) -> dict:
    return {"xmlPreview": _xml_preview(xml), "xmlPreviewTruncated": len(xml) > XML_PREVIEW_BYTES}


def _tpt_output_report(req: Request, direction: str, inp: dict, extract: TptExtract) -> dict:
    catalog = load_catalog(extract.version)
    return {
        "direction": direction,
        "input": {**inp, "source": extract.source, "outputVersion": extract.version}
        if inp.get("kind") != "fundsxml"
        else {**inp, "source": extract.source, "version": extract.version},
        "summary": {**extract.stats, "portfolioList": _portfolio_summary(extract.rows)},
        "coverage": _coverage_from_rows(extract.rows, catalog),
        "issues": [i.to_dict() for i in extract.issues],
        "validation": None,
        "preview": _preview(extract.rows, catalog),
        "xmlPreview": None,
    }


def _of_output_report(
    direction: str, inp: dict, extract: OfExtract, before: list[dict] | None = None
) -> dict:
    return {
        "direction": direction,
        "input": {**inp, "outputVersion": load_openfunds().version},
        "summary": {
            **extract.stats,
            "portfolioList": _shareclass_summary(extract.shareclasses, extract.holdings),
        },
        "coverage": _of_coverage_from_rows(extract.shareclasses + extract.holdings),
        "issues": (before or []) + [i.to_dict() for i in extract.issues],
        "validation": None,
        "preview": _of_preview(extract.shareclasses),
        "xmlPreview": None,
    }


# How the intermediate FundsXML document was written: no concern of a TPT or openfunds target, whose
# losses are reported as hop_data_loss.
_INTERMEDIATE_CODES = {
    "block_value_rejected",
    "core_value_rejected",
    "core_value_skipped",
    "schema_incomplete",
    "xsd_invalid",
    "control_data",
    "v8_in_v7_block",
    "of_template_incomplete",
    "of_template_rejected",
    "more_messages",
}


def _hop_issues(result: ConversionResult) -> list[dict]:
    """Issues of the conversion into the intermediate FundsXML document that concern the output."""
    return [
        {**i.to_dict(), "hop": "fundsxml"}
        for i in result.issues
        if i.level == "error" or i.code not in _INTERMEDIATE_CODES
    ]


def _not_carried(source: str, target: str, names: list[str]) -> list[dict]:
    if not names:
        return []
    shown = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
    return [
        Issue(
            "warning",
            "hop_data_loss",
            f"{len(names)} {source} field(s) have no place in {target} and are not in the output: {shown}",
            params={"n": len(names), "columns": shown, "source": source, "target": target},
        ).to_dict()
    ]


def _hop_loss(names: list[str], extract: TptExtract | None = None) -> dict:
    version = _version_loss(extract) if extract is not None else None
    return {
        "lost": len(names) + (version["lost"] if version else 0),
        "keptAsCustomAttribute": 0,
        "notInCoreStructures": 0,
        "codes": (["hop_data_loss"] if names else []) + (version["codes"] if version else []),
    }


# Values the TPT output version cannot hold (app.convert.to_tpt._adapt_version).
_VERSION_LOSS_CODES = ("v8_not_applicable_dropped", "v7_downgrade")


def _version_loss(extract: TptExtract) -> dict | None:
    """TPT values left out or changed to fit the output version; None if the version took everything."""
    counts = {i.code: (i.params or {}).get("n", 0) for i in extract.issues if i.code in _VERSION_LOSS_CODES}
    if not counts:
        return None
    return {
        "lost": sum(counts.values()),
        "keptAsCustomAttribute": 0,
        "notInCoreStructures": 0,
        "codes": sorted(counts),
    }


def _of_data_loss(result: ConversionResult) -> dict:
    totals = result.issue_totals
    lost = totals.get("of_value_lost", 0) + totals.get("of_holding_unassigned", 0)
    return {
        "lost": lost,
        "keptAsCustomAttribute": result.stats.get("custom_attributes", 0),
        "notInCoreStructures": 0,
        "codes": sorted(
            c for c in ("of_value_lost", "of_holding_unassigned", "core_value_rejected") if totals.get(c)
        ),
    }


def _check_fundsxml_size(root) -> None:
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


def _too_large(exc: TooManyRowsError) -> TooLargeError:
    return TooLargeError(
        f"{exc}; this service converts up to {settings.max_positions} per file – split it by portfolio"
    )


def _package(name: str, mime: str, data: bytes) -> OutputFile:
    if len(data) <= settings.zip_threshold_mb * 1024 * 1024:
        return OutputFile(data, name, mime)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(name, data)
    return OutputFile(buf.getvalue(), name + ".zip", "application/zip", zipped=True)


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


def _shareclass_summary(shareclasses: list[dict[str, str]], holdings: list[dict[str, str]]) -> list[dict]:
    """The share classes of an openfunds file in the shape of ``_portfolio_summary``."""
    positions: dict[str, int] = {}
    for h in holdings:
        key = h.get("OFST020000") or h.get("OFST020001") or ""
        positions[key] = positions.get(key, 0) + 1
    out = []
    for r in shareclasses:
        key = r.get("OFST020000") or r.get("OFST020001") or ""
        out.append(
            {
                "id": key,
                "date": r.get("OFDY000036") or r.get("OFDY000071") or r.get("OFDY100000", ""),
                "name": r.get("OFST020060") or r.get("OFST010020", ""),
                "currency": r.get("OFST020540", ""),
                "nav": r.get("OFDY000070", ""),
                "positions": positions.get(key, 0) or (positions.get("", 0) if len(shareclasses) == 1 else 0),
            }
        )
    return out


def _of_preview(rows: list[dict[str, str]]) -> dict:
    catalog = load_openfunds()
    return {
        "columns": [{"key": k, "name": catalog.by_id[k].name} for k in OF_PREVIEW_KEYS],
        "rows": [[r.get(k, "") for k in OF_PREVIEW_KEYS] for r in rows[:PREVIEW_ROWS]],
        "total": len(rows),
    }


def _of_name(col: str) -> str:
    catalog = load_openfunds()
    match = catalog.match_header(col)
    f = catalog.by_id.get(match.of_id) if match else None
    return f.name if f else col


def _of_coverage(coverage: dict[str, dict[str, bool]]) -> dict:
    """Where the openfunds columns of the input ended up (``block`` is always false)."""
    fields = [{"key": k, "name": _of_name(k), "block": False, **c} for k, c in coverage.items()]
    return {
        "present": len(fields),
        "block": 0,
        "core": sum(1 for f in fields if f["core"]),
        "custom": sum(1 for f in fields if f["custom"] and not f["core"]),
        "fields": fields,
    }


def _of_coverage_from_rows(rows: list[dict[str, str]]) -> dict:
    present = list(dict.fromkeys(k for r in rows for k, v in r.items() if v))
    fields = [
        {"key": k, "name": _of_name(k), "block": False, "core": False, "custom": False} for k in present
    ]
    return {
        "present": len(fields),
        "block": 0,
        "core": 0,
        "custom": 0,
        "fields": fields,
        "total": sum(1 for f in load_openfunds().fields if f.active),
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
