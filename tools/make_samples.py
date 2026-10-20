"""Build the bundled example files from findatex-validator's showcase TPT.

Fund A of 00_showcase.xlsx is clean (20 positions: bonds, equities, ETFs, a
future, an option, cash). From it:

* tpt_v7_sample.xlsx  – the rows as TPT V7
* tpt_v8_sample.xlsx  – the same as TPT V8 (fields 150/151, NACE header, codes)
* fundsxml_sample.xml – the V7 sample converted with this app

Usage: python tools/make_samples.py [path/to/findatex-validator]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from openpyxl import Workbook, load_workbook  # noqa: E402

from app.convert.to_fundsxml import convert_tpt_to_fundsxml  # noqa: E402
from app.ingest.tpt_reader import read_tpt  # noqa: E402
from app.spec.catalog import VERSION_LABELS  # noqa: E402

OUT = ROOT / "backend" / "app" / "samples"


def main() -> None:
    src_root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "findatex-validator"
    wb = load_workbook(src_root / "samples" / "tpt" / "00_showcase.xlsx", read_only=True)
    rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    header, body = rows[0], rows[1:]
    fund_a = body[0][0]
    body = [r for r in body if r[0] == fund_a]
    OUT.mkdir(parents=True, exist_ok=True)

    _save(OUT / "tpt_v7_sample.xlsx", "TPT V7.0", header, body)

    v8_header = ["148_Economic_sector_NACE" if h == "148_Economic_sector_NACE2.1" else h for h in header]
    v8_header += ["150_LTEI_Fund_Elligibility", "151_Legislative_program_investment"]
    i1000 = header.index("1000_TPT_Version")
    v8_body = []
    for r in body:
        r = list(r)
        r[i1000] = VERSION_LABELS["V8"]
        v8_body.append(r + ["0", "0"])
    _save(OUT / "tpt_v8_sample.xlsx", "TPT V8.0", v8_header, v8_body)

    data = (OUT / "tpt_v7_sample.xlsx").read_bytes()
    result = convert_tpt_to_fundsxml(read_tpt(data, "tpt_v7_sample.xlsx"))
    (OUT / "fundsxml_sample.xml").write_bytes(result.xml)
    print(f"{len(body)} positions; FundsXML valid: {result.valid}", *result.validation_errors[:5], sep="\n")


def _save(path: Path, title: str, header: list, body: list) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for r in body:
        ws.append(r)
    wb.save(path)


if __name__ == "__main__":
    main()
