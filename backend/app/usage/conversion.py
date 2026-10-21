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

_SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples"


@lru_cache(maxsize=1)
def _sample_digests() -> frozenset[str]:
    return frozenset(hashlib.sha256(p.read_bytes()).hexdigest() for p in _SAMPLE_DIR.iterdir() if p.is_file())


def is_sample(data: bytes) -> bool:
    """The upload is one of the bundled examples ("Try an example" uploads it unchanged)."""
    return hashlib.sha256(data).hexdigest() in _sample_digests()


def conversion_fields(req: ConvertRequest, result: dict) -> dict:
    inp = result.get("input") or {}
    summary = result.get("summary") or {}
    issues = result.get("issues") or []
    validation = result.get("validation")
    output = result.get("output") or {}
    to_fundsxml = result.get("direction") == "tpt-to-fundsxml"
    fields: dict = {
        "direction": result.get("direction"),
        "source": "sample" if is_sample(req.data) else inp.get("format") or "xml",
        "tpt_version": inp.get("version"),
        "schema_name": f"TPT {inp.get('version')}" if to_fundsxml else "FundsXML 4",
        "target_namespace": "FundsXML 4" if to_fundsxml else f"TPT {inp.get('version')}",
        "output_format": "xml" if to_fundsxml else req.output_format,
        "input_bytes": len(req.data),
        "file_count": summary.get("portfolios"),
        "element_count": summary.get("positions"),
        "diagnostic_count": len(issues),
        "error_count": len(validation["errors"])
        if validation
        else sum(1 for i in issues if i.get("level") == "error"),
        "issue_codes": sorted({i["code"] for i in issues if i.get("code")}),
        "valid": validation["valid"] if validation else None,
        "zipped": output.get("zipped"),
    }
    if to_fundsxml:
        fields |= {
            "version_source": inp.get("versionSource"),
            "type_count": inp.get("columns"),
            "include_block": req.include_block,
            "include_core": req.include_core,
        }
    return fields
