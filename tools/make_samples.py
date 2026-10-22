"""Build the bundled example files (backend/app/samples, served by /api/samples).

From findatex-validator's showcase TPT (Fund A of 00_showcase.xlsx: 20 clean positions):

* tpt_v7_sample.xlsx      – the rows as TPT V7
* tpt_v8_sample.xlsx      – the same as TPT V8 (fields 150/151, NACE header, codes)
* fundsxml_sample.xml     – the V7 sample converted with this app
* openfunds_sample.xlsx   – the V7 sample as openfunds holdings, its share class with static data

From the synthetic data in sample_data.py:

* tpt_all_cic.xlsx               – one position per CIC category 0–9, A–F and their variants
* tpt_multi_fund.xlsx            – two funds, the first with three share classes (one in USD)
* tpt_semicolon.csv              – tpt_all_cic as CSV with ";"
* tpt_with_errors.xlsx           – typical delivery errors
* fundsxml_all_cic.xml           – tpt_all_cic converted (core structures + TPT block)
* fundsxml_core_only.xml         – tpt_all_cic converted without the TPT block
* fundsxml_fund_portfolio.xml    – one fund with three share classes sharing the fund portfolio
* fundsxml_from_openfunds.xml    – openfunds_static converted: rich static and dynamic data
* fundsxml_with_errors.xml       – an older TPT block, a core/block mismatch, missing values
* openfunds_multi.xlsx           – tpt_multi_fund as openfunds (OF-ID header, static data)
* openfunds_static.xlsx          – rich static and dynamic data of four share classes, holdings for one
* openfunds_csv.zip              – share classes and holdings of tpt_all_cic as two CSV files
* openfunds_with_errors.xlsx     – unknown columns, invalid values, holdings without share class

Usage: python tools/make_samples.py [path/to/findatex-validator]
       python tools/make_samples.py --synthetic   (only the files from sample_data.py)
"""

from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import sample_data as sd
from app.convert.derive import amount
from app.convert.fundsxml_to_openfunds import extract_openfunds
from app.convert.openfunds_to_fundsxml import convert_openfunds_to_fundsxml
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.openfunds_reader import read_openfunds
from app.ingest.tpt_reader import read_tpt
from app.model.xmltree import Node, serialize_at
from app.schema.model import fundsxml_model
from app.spec.catalog import VERSION_LABELS
from app.validate.xsd import validate_fundsxml
from app.writers.openfunds_writer import write_openfunds
from app.writers.tpt_writer import write_csv, write_xlsx
from lxml import etree
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

# V8 extras of the showcase rows: LTEI eligibility (150) for fund shares, legislative programmes (151)
# for equities, the securitisation sub-types e1–e3 (56) do not occur in the showcase.
V8_EXTRAS = {"4": ("1", "0"), "3": ("0", "2")}


def _write(name: str, data: bytes) -> None:
    (OUT / name).write_bytes(data)


def _tpt(rows: list[dict], version: str = "V7") -> bytes:
    return write_xlsx(rows, version, all_columns=False)


def _fundsxml(name: str, data: bytes, filename: str, block: bool = True) -> bytes:
    result = convert_tpt_to_fundsxml(read_tpt(data, filename), ConvertOptions(include_block=block))
    print(f"{name}: valid {result.valid}", *result.validation_errors[:3], sep="\n  ")
    _write(name, result.xml)
    return result.xml


# Share class identity and figures of the converted data, never replaced by the static data.
IDENTITY = ("OFST020000", "OFST020060", "OFST020540", "OFDY000035", "OFDY000036", "OFDY000070", "OFDY000071")


def _openfunds(name: str, xml: bytes, static: dict | list[dict] | None, **kw) -> tuple[list, list]:
    extract = extract_openfunds(parse_fundsxml(xml), non_openfunds_columns=False)
    for i, record in enumerate(extract.shareclasses):
        extra = static[i % len(static)] if isinstance(static, list) else static or {}
        # Keep the identity of the converted share class: its holdings refer to its ISIN.
        record.update({k: v for k, v in extra.items() if k not in IDENTITY or k not in record})
    data, _, _ = write_openfunds(extract.shareclasses, extract.holdings, **kw)
    _write(name, data)
    print(f"{name}: {len(extract.shareclasses)} share class(es), {len(extract.holdings)} holdings")
    return extract.shareclasses, extract.holdings


# -- from the showcase -----------------------------------------------------------------------


def make_showcase(src_root: Path) -> None:
    wb = load_workbook(src_root / "samples" / "tpt" / "00_showcase.xlsx", read_only=True)
    rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    header, body = rows[0], rows[1:]
    fund_a = body[0][0]
    body = [r for r in body if r[0] == fund_a]

    _save(OUT / "tpt_v7_sample.xlsx", "TPT V7.0", header, body)

    v8_header = ["148_Economic_sector_NACE" if h == "148_Economic_sector_NACE2.1" else h for h in header]
    v8_header += ["150_LTEI_Fund_Elligibility", "151_Legislative_program_investment"]
    i1000, i12 = header.index("1000_TPT_Version"), header.index("12_CIC_code_of_the_instrument")
    v8_body = []
    for r in body:
        r = list(r)
        r[i1000] = VERSION_LABELS["V8"]
        v8_body.append(r + list(V8_EXTRAS.get(str(r[i12])[2:3], ("0", "0"))))
    _save(OUT / "tpt_v8_sample.xlsx", "TPT V8.0", v8_header, v8_body)

    xml = _fundsxml("fundsxml_sample.xml", (OUT / "tpt_v7_sample.xlsx").read_bytes(), "tpt_v7_sample.xlsx")
    _openfunds("openfunds_sample.xlsx", xml, OPENFUNDS_STATIC, header_names=True)


# -- synthetic -------------------------------------------------------------------------------


def make_synthetic() -> None:
    all_cic, multi = sd.all_cic_rows(), sd.multi_fund_rows()
    _write("tpt_all_cic.xlsx", _tpt(all_cic))
    _write("tpt_multi_fund.xlsx", _tpt(multi))
    _write("tpt_semicolon.csv", write_csv(all_cic, "V7", ";", all_columns=False))
    _write("tpt_with_errors.xlsx", _tpt(sd.error_rows()))
    print(f"TPT: {len(all_cic)} positions (all CIC), {len(multi)} rows (multi fund)")

    all_cic_xml = _fundsxml("fundsxml_all_cic.xml", _tpt(all_cic), "all_cic.xlsx")
    _fundsxml("fundsxml_core_only.xml", _tpt(all_cic), "all_cic.xlsx", block=False)
    multi_xml = convert_tpt_to_fundsxml(
        read_tpt(_tpt(multi), "multi.xlsx"), ConvertOptions(include_block=False)
    ).xml
    _write_checked("fundsxml_fund_portfolio.xml", fund_portfolio(multi_xml))

    _write("fundsxml_with_errors.xml", fundsxml_errors(all_cic_xml))
    _openfunds("openfunds_multi.xlsx", multi_xml, sd.OF_MULTI_STATIC)
    shareclasses, holdings = _openfunds(
        "openfunds_csv.zip", all_cic_xml, sd.OF_SHARECLASSES[0], output_format="csv"
    )
    _write("openfunds_with_errors.xlsx", openfunds_errors(shareclasses, holdings))

    # Holdings for the first share class only: the others have static and dynamic data alone.
    static = sd.OF_SHARECLASSES + [sd.OF_ETF]
    owned = [{**h, "OFST020000": static[0]["OFST020000"]} for h in holdings]
    data, filename, _ = write_openfunds(static, owned, header_names=True)
    _write("openfunds_static.xlsx", data)
    result = convert_openfunds_to_fundsxml(read_openfunds(data, filename))
    print(f"fundsxml_from_openfunds.xml: valid {result.valid}", *result.validation_errors[:3], sep="\n  ")
    _write("fundsxml_from_openfunds.xml", result.xml)


def fund_portfolio(xml: bytes) -> bytes:
    """The share classes of fund A in one fund, sharing its portfolio in FundDynamicData; fund B
    without share classes (identifiers, NAV and portfolio on the fund)."""
    root = parse_fundsxml(xml)
    funds = _node(root.find("Funds"))
    classes = funds.children[:3]
    fund = classes[0]
    share_classes = fund.find("SingleFund/ShareClasses")
    for other in classes[1:]:
        share_classes.children += other.find("SingleFund/ShareClasses").children
        funds.children.remove(other)
    fund.set("Names/OfficialName", "Demo Balanced Fund")
    fund.ensure("Identifiers").set("LEI", sd.lei("529900DEMOBALANCED"))
    first = share_classes.children[0]
    portfolio = first.find("Portfolios").children[0]
    dynamic = Node("FundDynamicData")
    nav = dynamic.ensure("TotalAssetValues").add("TotalAssetValue")
    nav.set("NavDate", sd.VALUATION)
    nav.set("TotalAssetNature", "OFFICIAL")
    # The fund portfolio is the EUR class's book; the classes hold half, 30 % and 20 % of it.
    total = Decimal(first.find("TotalAssetValues/TotalAssetValue/TotalNetAssetValue/Amount").text)
    nav.set("TotalNetAssetValue/Amount[@ccy=EUR]", amount(total))
    for sc, part in zip(share_classes.children, ("0.5", "0.3", "0.2"), strict=True):
        _share_of(sc, total * Decimal(part))
    dynamic.ensure("Portfolios").children.append(portfolio)
    fund.children.append(dynamic)
    for sc in share_classes.children:
        sc.children = [c for c in sc.children if c.name != "Portfolios"]
    _without_share_classes(funds.children[1])
    res = serialize_at(fundsxml_model(), funds, ["Funds"])
    assert not res.dropped and not res.invalid, res.dropped[:3] + res.invalid[:3]
    root.replace(root.find("Funds"), res.element)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _without_share_classes(fund: Node) -> None:
    sc = fund.find("SingleFund/ShareClasses").children[0]
    fund.children = [c for c in fund.children if c.name not in ("Identifiers", "SingleFund")]
    fund.children.insert(0, sc.find("Identifiers"))
    dynamic = fund.ensure("FundDynamicData")
    dynamic.children += [sc.find("TotalAssetValues"), sc.find("Portfolios")]


def _share_of(sc: Node, eur: Decimal) -> None:
    """Set the class's NAV to ``eur`` (in its currency) and its price to NAV / shares."""
    tav = sc.find("TotalAssetValues/TotalAssetValue")
    amount_node = tav.find("TotalNetAssetValue/Amount")
    nav = eur / (sd.RATES[amount_node.attrs["ccy"]] / sd.RATES["EUR"])
    amount_node.text = amount(nav)
    price = (nav / Decimal(tav.find("SharesOutstanding").text)).quantize(Decimal("0.0001"))
    sc.find("Prices/Price").set("NavPrice", str(price))


def _node(el: etree._Element) -> Node:
    node = Node(el.tag, el.text.strip() if el.text and el.text.strip() else None)
    node.attrs = dict(el.attrib)
    node.children = [_node(c) for c in el if isinstance(c.tag, str)]
    return node


def _write_checked(name: str, xml: bytes) -> None:
    valid, errors = validate_fundsxml(etree.fromstring(xml))
    print(f"{name}: valid {valid}", *errors[:3], sep="\n  ")
    _write(name, xml)


def fundsxml_errors(xml: bytes) -> bytes:
    """Deliberately faulty input: edits of a valid document the converter must report.

    * an additional TripartiteTemplateSolvencyII_V6 block (not read: older_tpt_block),
    * a core position removed, so core and TPT block disagree (core_mismatch),
    * the instrument name and market values of a block position removed (mandatory_missing).
    """
    root = parse_fundsxml(xml)
    indirect = root.find("RegulatoryReportings/IndirectReporting")
    v7 = indirect.find("TripartiteTemplateSolvencyII_V7")
    v6 = copy.deepcopy(v7)
    v6.tag = "TripartiteTemplateSolvencyII_V6"
    indirect.insert(list(indirect).index(v7), v6)
    core_positions = root.find("Funds/Fund/SingleFund/ShareClasses/ShareClass/Portfolios/Portfolio/Positions")
    core_positions.remove(core_positions[-1])
    position = v7.find("Portfolio/Positions/Position")
    for path in ("InstrumentName", "Valuation/MarketValueQC", "Valuation/MarketValuePC"):
        el = position.find(path)
        el.getparent().remove(el)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def openfunds_errors(shareclasses: list[dict], holdings: list[dict]) -> bytes:
    """openfunds data with an unknown OF-ID, a non-openfunds column, invalid values and holdings
    of a share class the file does not contain (with two share classes, so it cannot be assigned)."""
    sc = {**shareclasses[0], "OFST999999": "x", "Internal Rating": "AA"}
    sc.update({"OFST020560": "15.03.2015", "OFST020400": "sometimes", "OFST452010": "1,5 %"})
    sc.pop("OFST020540", None)
    second = {**sd.OF_SHARECLASSES[1], "OFST020060": ""}  # name missing
    orphan = {**holdings[1], "OFST020000": sd.isin("LU2900NOSC0")}
    bad = {**holdings[2], "OFPH000300": "viel"}
    return write_openfunds([sc, second], [holdings[0], bad, orphan, *holdings[3:6]])[0]


def _save(path: Path, title: str, header: list, body: list) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(header)
    for r in body:
        ws.append(r)
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.argv[1:] != ["--synthetic"]:
        make_showcase(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "findatex-validator")
    make_synthetic()


if __name__ == "__main__":
    main()
