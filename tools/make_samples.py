"""Build the bundled example files from findatex-validator's showcase TPT.

Fund A of 00_showcase.xlsx is clean (20 positions: bonds, equities, ETFs, a
future, an option, cash). From it:

* tpt_v7_sample.xlsx  – the rows as TPT V7
* tpt_v8_sample.xlsx  – the same as TPT V8 (fields 150/151, NACE header, codes)
* fundsxml_sample.xml – the V7 sample converted with this app
* openfunds_sample.xlsx – the V7 sample as openfunds holdings, its share class with typical
  openfunds static data

Usage: python tools/make_samples.py [path/to/findatex-validator]
       python tools/make_samples.py --openfunds   (only the openfunds sample, from tpt_v7_sample.xlsx)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.convert.fundsxml_to_openfunds import extract_openfunds
from app.convert.to_fundsxml import convert_tpt_to_fundsxml
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.tpt_reader import read_tpt
from app.spec.catalog import VERSION_LABELS
from app.writers.openfunds_writer import write_openfunds
from openpyxl import Workbook, load_workbook

OUT = ROOT / "backend" / "app" / "samples"


# Static data of the sample share class as an openfunds sender would deliver it.
OPENFUNDS_STATIC = {
    "OFST001000": "Demo Asset Management",
    "OFST001020": "Demo Asset Management S.A.",
    "OFST001035": "LU",
    "OFST001400": "Demo Custodian Bank S.A.",
    "OFST001410": "529900WL9GZRMTQJ4B19",
    "OFST001600": "Demo Audit S.à r.l.",
    "OFST010010": "LU",
    "OFST010240": "2015-03-02",
    "OFST010410": "EUR",
    "OFST010420": "open-ended fund",
    "OFST160040": "UCITS",
    "OFST020050": "A",
    "OFST020400": "distributing",
    "OFST020560": "2015-03-02",
    "OFST023100": "open",
    "OFST452010": "0.012",
    "OFST6030AT": "yes",
    "OFST6030DE": "yes",
    "OFST6030LU": "yes",
}


def make_openfunds() -> None:
    data = (OUT / "tpt_v7_sample.xlsx").read_bytes()
    fx = convert_tpt_to_fundsxml(read_tpt(data, "tpt_v7_sample.xlsx"))
    extract = extract_openfunds(parse_fundsxml(fx.xml), non_openfunds_columns=False)
    for record in extract.shareclasses:
        record.update(OPENFUNDS_STATIC)
    out, _, _ = write_openfunds(extract.shareclasses, extract.holdings, header_names=True)
    (OUT / "openfunds_sample.xlsx").write_bytes(out)
    print(f"openfunds: {len(extract.shareclasses)} share class(es), {len(extract.holdings)} holdings")


def main() -> None:
    if sys.argv[1:] == ["--openfunds"]:
        make_openfunds()
        return
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
    make_openfunds()


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
