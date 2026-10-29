"""Copy the TPT spec catalogs from a findatex-validator checkout into backend/app/spec/.

The validator builds one JSON catalog per TPT version from the official FinDatEx
workbooks (core/target/classes/spec/tpt/*.catalog.json, written by
CatalogSnapshotGenerator). This script copies them and strips known parser
artifacts, so the converter never offers a code that is not in the spec.

Usage: python tools/sync_specs.py [path/to/findatex-validator]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "backend" / "app" / "spec"
CATALOGS = {
    "tpt_v7.json": "TPT_V7_20241125.catalog.json",
    "tpt_v8.json": "TPT_V8_20261008.catalog.json",
}
# Codes the workbook parser picked up from prose, not real closed-list entries.
BOGUS_CODES = {"56": {"securitisation"}}
KEEP = ("numData", "name", "fundXmlPath", "definition", "codification", "flags", "applicableCic")
# The V8 workbook names the full XPath of the V8 block (FundsXML 4.2.12); keep the path below the block.
PATH_PREFIXES = ("/FundsXML4/RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V8/", ".../")


def num_key(num_data: str) -> str:
    return num_data.split("_", 1)[0]


def clean(field: dict) -> dict:
    out = {k: field.get(k) for k in KEEP}
    cod = dict(out["codification"] or {})
    cod.pop("rawText", None)
    bogus = BOGUS_CODES.get(num_key(field["numData"]), set())
    cod["closedList"] = [c for c in cod.get("closedList", []) if c["code"] not in bogus]
    out["codification"] = cod
    path = (out.get("fundXmlPath") or "").strip()
    for prefix in PATH_PREFIXES:
        path = path.removeprefix(prefix)
    out["fundXmlPath"] = path or None
    out["numKey"] = num_key(field["numData"])
    return out


def main() -> None:
    src_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "findatex-validator"
    src_dir = src_root / "core" / "target" / "classes" / "spec" / "tpt"
    TARGET.mkdir(parents=True, exist_ok=True)
    for target_name, src_name in CATALOGS.items():
        data = json.loads((src_dir / src_name).read_text(encoding="utf-8"))
        fields = [clean(f) for f in data["fields"]]
        payload = {"source": src_name, "fingerprint": data.get("fingerprint"), "fields": fields}
        (TARGET / target_name).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
        print(f"{target_name}: {len(fields)} fields")


if __name__ == "__main__":
    main()
