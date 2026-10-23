"""The usage-event fields of one conversion – counts and classes only.

``service.run`` returns the full report for the browser; this picks the
aggregate, non-identifying parts of it. Never the file name, portfolio ids,
names or NAVs, cell values or issue messages: only issue *codes*.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.model.xmltree import parse_date
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


_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def fund_fields(isins, nav_dates, secret: str | None, today: date) -> dict:
    """What the statistics keep of the share classes converted – never an ISIN or a date as such.

    * ``isin_countries``: the ISINs' country prefixes (LU, IE, AT …);
    * ``fund_keys``: a keyed fingerprint per ISIN (HMAC with the usage hash secret), so distinct and
      repeatedly converted share classes can be counted; without the secret it cannot be reversed or
      matched against an ISIN list. None without a secret;
    * ``nav_months``: the valuation dates' months (2026-09);
    * ``data_age_days``: days from the latest valuation date to the conversion.
    """
    valid = sorted({i.strip().upper() for i in isins if i and _ISIN.fullmatch(i.strip().upper())})
    dates = []
    for value in nav_dates:
        try:
            dates.append(parse_date(value))
        except (ValueError, TypeError):
            continue
    out: dict = {
        "isin_countries": sorted({i[:2] for i in valid}),
        "nav_months": sorted({d.strftime("%Y-%m") for d in dates}),
        "data_age_days": (today - max(dates)).days if dates else None,
    }
    if secret:
        out["fund_keys"] = [
            hmac.new(secret.encode(), f"fund|{i}".encode(), hashlib.sha256).hexdigest()[:20] for i in valid
        ]
    return out


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


def conversion_fields(req: ConvertRequest, result: dict, secret: str | None = None) -> dict:
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
        **fund_fields(
            req.telemetry.get("isins", ()), req.telemetry.get("nav_dates", ()), secret, date.today()
        ),
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
