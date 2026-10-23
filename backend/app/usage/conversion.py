"""The usage-event fields of one conversion – counts and classes only.

``service.run`` returns the full report for the browser; this picks the
aggregate, non-identifying parts of it. Never the file name, portfolio ids,
names or NAVs, cell values or issue messages: only issue *codes*.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from app.service import Request as ConvertRequest
from app.writers.tpt_writer import CSV_DELIMITERS

# Delimiter character -> the option name the form uses (semicolon, comma, pipe, tab).
_DELIMITER_NAMES = {char: name for name, char in CSV_DELIMITERS.items()}

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples"


@lru_cache(maxsize=1)
def _sample_digests() -> frozenset[str]:
    return frozenset(hashlib.sha256(p.read_bytes()).hexdigest() for p in _SAMPLE_DIR.iterdir() if p.is_file())


def is_sample(data: bytes) -> bool:
    """The upload is one of the bundled examples ("Try an example" uploads it unchanged)."""
    return hashlib.sha256(data).hexdigest() in _sample_digests()


def _format_name(kind: str, version: str | None) -> str:
    return {"tpt": f"TPT {version}", "fundsxml": "FundsXML 4", "openfunds": f"openfunds {version}"}.get(
        kind, kind
    )


# Request.telemetry keys taken over as they are (counts and classes, see app.service).
_TELEMETRY = frozenset(
    {"of_layout", "of_templates", "shareclass_count", "holding_count", "asset_count"}
    | {"has_tpt_block", "cic_categories"}
)


def request_options(req: ConvertRequest, source: str, target: str) -> list[str]:
    """The options set away from their default that apply to this direction, as fixed names."""
    supplier = bool(req.data_supplier_name or req.data_supplier_short or req.data_supplier_country)
    pair = (source, target)
    flags = {
        "tpt_version_forced": bool(req.tpt_version) and "tpt" in (source, target),
        "of_header_names": req.of_header_names and target == "openfunds",
        "no_non_openfunds_columns": not req.non_openfunds_columns and pair == ("tpt", "openfunds"),
        "no_implied_tpt_attributes": not req.implied_tpt_attributes and pair == ("openfunds", "fundsxml"),
        "data_supplier": supplier and target == "fundsxml",
        "no_preview": not req.preview,
    }
    return sorted(name for name, on in flags.items() if on)


def _coverage_pct(coverage: dict) -> float | None:
    """→ FundsXML: the share of the source fields placed in the TPT block or core structures."""
    fields = coverage.get("fields") or []
    if not fields or "total" in coverage:
        return None
    placed = sum(1 for f in fields if f.get("block") or f.get("core"))
    return round(100 * placed / len(fields), 1)


def conversion_fields(req: ConvertRequest, result: dict) -> dict:
    inp = result.get("input") or {}
    summary = result.get("summary") or {}
    issues = result.get("issues") or []
    validation = result.get("validation")
    output = result.get("output") or {}
    loss = result.get("dataLoss") or {}
    source, _, target = (result.get("direction") or "").partition("-to-")
    in_version = inp.get("version")
    out_version = inp.get("outputVersion") or (in_version if source == "fundsxml" else None)
    fields: dict = {
        "direction": result.get("direction"),
        "source": "sample" if is_sample(req.data) else inp.get("format") or "xml",
        "tpt_version": in_version if source == "tpt" else (out_version if target == "tpt" else None),
        "schema_name": _format_name(source, in_version),
        "target_namespace": _format_name(target, out_version),
        "output_format": "xml" if target == "fundsxml" else req.output_format,
        "input_bytes": len(req.data),
        "file_count": summary.get("portfolios", summary.get("shareclasses")),
        "element_count": summary.get("positions"),
        "diagnostic_count": len(issues),
        "error_count": len(validation["errors"])
        if validation
        else sum(1 for i in issues if i.get("level") == "error"),
        "issue_codes": sorted({i["code"] for i in issues if i.get("code")}),
        "valid": validation["valid"] if validation else None,
        "zipped": output.get("zipped"),
        "output_bytes": output.get("size"),
        "source_format": source or None,
        "target_format": target or None,
        "warning_count": sum(1 for i in issues if i.get("level") == "warning"),
        "info_count": sum(1 for i in issues if i.get("level") == "info"),
        "values_lost": loss.get("lost"),
        "values_kept_custom": loss.get("keptAsCustomAttribute"),
        "coverage_pct": _coverage_pct(result.get("coverage") or {}),
        "options": request_options(req, source, target),
        **{k: v for k, v in req.telemetry.items() if k in _TELEMETRY},
    }
    if source == "tpt":
        fields |= {"version_source": inp.get("versionSource"), "type_count": inp.get("columns")}
        if target == "fundsxml":
            fields |= {"include_block": req.include_block, "include_core": req.include_core}
    if target == "fundsxml":
        # CSV input: the delimiter the reader detected.
        fields["delimiter"] = (
            _DELIMITER_NAMES.get(inp.get("delimiter") or "") if inp.get("format") == "csv" else None
        )
    else:
        fields |= {
            # CSV output: the delimiter written (an unknown choice falls back to semicolon).
            "delimiter": (req.delimiter if req.delimiter in CSV_DELIMITERS else "semicolon")
            if req.output_format == "csv"
            else None,
            # Effective choice: every TPT column unless declined, every openfunds column only on request.
            "all_columns": req.all_columns if req.all_columns is not None else target == "tpt",
        }
    return fields
