"""TPT → FundsXML → TPT must give back every value (numbers and dates compared by value).

Fields the source leaves empty may come back filled when FundsXML implies them (``DERIVED_FIELDS``).
"""

from __future__ import annotations

import pytest

from app.convert.derive import DERIVED_FIELDS
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml
from app.convert.to_tpt import extract_tpt
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.tpt_reader import read_tpt
from app.mapping.transforms import ASSET_TYPE, POSITION_ELEMENT, RATE_TYPE, ZERO_COUPON_RATE
from app.model.xmltree import parse_date, parse_decimal

FILES = [
    "00_showcase.xlsx",
    "01_clean.xlsx",
    "02_missing_mandatory.csv",
    "10_dates_and_derivatives.xlsx",
    "12_multi_fund_clean.xlsx",
    "tpt_v7_sample.xlsx",
    "tpt_v8_sample.xlsx",
    "tpt_all_cic.xlsx",
    "tpt_multi_fund.xlsx",
    "tpt_semicolon.csv",
]


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    for parse in (parse_decimal, parse_date):
        try:
            if parse(a) == parse(b):
                return True
        except ValueError:
            continue
    return False


def _diffs(doc, rows):
    assert len(rows) == len(doc.rows)
    out = []
    for orig, back in zip(doc.rows, rows, strict=True):
        for key in set(orig.values) | set(back):
            if key == "1000" and doc.version == "V7":
                continue  # the label is normalised to the official one
            if key in DERIVED_FIELDS and not orig.values.get(key):
                continue
            if not _same(orig.values.get(key, ""), back.get(key, "")):
                out.append((orig.source_row, key, orig.values.get(key), back.get(key)))
    return out


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("block,core", [(True, True), (False, True)])
def test_lossless_roundtrip(fixture_bytes, name, block, core):
    doc = read_tpt(fixture_bytes(name), name)
    result = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block, include_core=core))
    extract = extract_tpt(parse_fundsxml(result.xml))
    assert extract.version == doc.version
    assert _diffs(doc, extract.rows) == []


@pytest.mark.parametrize(
    "name", ["tpt_v7_sample.xlsx", "tpt_v8_sample.xlsx", "tpt_all_cic.xlsx", "tpt_multi_fund.xlsx"]
)
@pytest.mark.parametrize("block", [True, False])
def test_complete_files_are_schema_valid(fixture_bytes, name, block):
    doc = read_tpt(fixture_bytes(name), name)
    result = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block))
    assert result.valid, result.validation_errors[:5]


def test_gaps_in_the_source_are_reported(fixture_bytes):
    # The multi-fund fixture has no quantities (18/19) and no exposures (27/28/30).
    doc = read_tpt(fixture_bytes("12_multi_fund_clean.xlsx"), "multi.xlsx")
    result = convert_tpt_to_fundsxml(doc)
    assert result.valid is False
    assert any("MarketExposureQC" in e for e in result.validation_errors)
    assert any(i.code == "schema_incomplete" for i in result.issues)


def test_v8_specifics_survive(fixture_bytes):
    data = fixture_bytes("tpt_v8_sample.xlsx")
    doc = read_tpt(data, "v8.xlsx")
    doc.rows[0].values["56"] = "e2"
    doc.rows[0].values.update({"47": "DE811907980", "48": "2"})
    result = convert_tpt_to_fundsxml(doc)
    xml = result.xml.decode()
    assert "<TPTVersion>V7.0</TPTVersion>" in xml
    assert "TPT_150_LTEI_Fund_Eligibility" in xml
    assert "TPT_48_Type_of_identification_code_for_issuer" in xml  # the V7 block only knows 1 and 9
    rows = extract_tpt(parse_fundsxml(result.xml)).rows
    assert rows[0]["56"] == "e2"
    assert rows[0]["48"] == "2"
    assert rows[0]["150"] == "0"
    assert rows[0]["1000"] == "V8.0 (official) dated 8 October 2026"


NOT_APPLICABLE_V8 = {
    *("17b", "29", "31", "35", "36", "44", "54", "58b", "106"),
    *("108", "114", "116", "118", "120", "124", "125", "126", "141"),
}


def test_v8_no_longer_maintained_fields():
    """The 18 fields of the Technical Annex "retained but no longer maintained" are N/A in the V8 catalog."""
    from app.spec.catalog import load_catalog

    assert load_catalog("V8").not_applicable_keys() == NOT_APPLICABLE_V8
    assert load_catalog("V7").not_applicable_keys() < NOT_APPLICABLE_V8


def test_v8_output_leaves_unmaintained_fields_empty(fixture_bytes):
    """V7 data (fund issuer code types 116/120, NACE 54 …) written as V8: those fields stay empty."""
    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    assert {"116", "120", "54"} <= set(doc.rows[0].values)
    extract = extract_tpt(parse_fundsxml(convert_tpt_to_fundsxml(doc).xml), "V8")
    assert extract.version == "V8"
    assert not any(NOT_APPLICABLE_V8 & set(r) for r in extract.rows)
    assert extract.rows[0]["1000"] == "V8.0 (official) dated 8 October 2026"
    (issue,) = [i for i in extract.issues if i.code == "v8_not_applicable_dropped"]
    assert "116_Fund_issuer_code_type" in issue.params["fields"] and issue.params["n"] > 0
    # Reading such a V8 file back warns, and the values still reach FundsXML (the V7 block has them).
    doc8 = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx", version="V8")
    (warning,) = [i for i in doc8.issues if i.code == "v8_not_applicable"]
    assert "54_Economic_sector" in warning.params["fields"]
    assert "<EconomicSector>" in convert_tpt_to_fundsxml(doc8).xml.decode()


def test_v8_data_keeps_the_v7_block_complete(fixture_bytes):
    """The V7 block requires 116/118/120, 36 and 44, which V8 no longer has: they are filled from V8
    data, and the V8 issuer code type 2 is written as 9, so no subtree is dropped."""
    from lxml import etree

    doc = read_tpt(fixture_bytes("tpt_v8_sample.xlsx"), "v8.xlsx")
    floater = next(r for r in doc.rows if r.values.get("34"))
    floater.values.pop("36", None)
    floater.values.setdefault(
        "33", "3.5"
    )  # the V7 block needs a coupon rate; the showcase floaters have none
    callable_bond = next(r for r in doc.rows if r.values.get("39") and r is not floater)
    callable_bond.values.update(
        {"42": "Cal", "43": "2028-06-30", "45": "100", "48": "2", "47": "DE811907980"}
    )
    result = convert_tpt_to_fundsxml(doc)
    rejected = [
        i for i in result.issues if i.code == "block_value_rejected" and i.row == callable_bond.source_row
    ]
    assert [i.field for i in rejected] == ["47"]  # a VAT ID is not an LEI; nothing else of the row is lost
    root = etree.fromstring(result.xml)
    block = root.find("RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7/Portfolio")
    qrt = block.find("QRTPortfolioInformation")
    assert qrt.findtext("FundIssuer/CodeType") == "1" and qrt.findtext("FundIssuer/EconomicSector") == "K6430"
    assert qrt.findtext("FundIssuerGroup/CodeType") == "1" and qrt.findtext("FundCIC")
    positions = block.findall("Positions/Position")
    by_row = {r.source_row: p for r, p in zip(doc.rows, positions, strict=True)}
    option = by_row[callable_bond.source_row].find("InterestRateInstrumentCharacteristics/EmbeddedOption")
    assert option.findtext("OptionDirection") == "I" and option.findtext("CallPutDate") == "2028-06-30"
    issuer = by_row[callable_bond.source_row].find("CreditRiskData/InstrumentIssuer")
    assert issuer.findtext("CodeType") == "9" and issuer.findtext("Name")
    variable = by_row[floater.source_row].find("InterestRateInstrumentCharacteristics/VariableRate")
    assert variable.findtext("IndexName") == floater.values["34"]
    # Back as V8: the fillers are N/A fields and vanish, the original values come back.
    rows = {r["14"]: r for r in extract_tpt(parse_fundsxml(result.xml), "V8").rows}
    back = rows[callable_bond.values["14"]]
    assert (back["48"], back["47"], back.get("44"), back.get("116")) == ("2", "DE811907980", None, None)
    assert rows[floater.values["14"]].get("36") is None
    # Back as V7: a complete V7 file.
    v7 = {r["14"]: r for r in extract_tpt(parse_fundsxml(result.xml), "V7").rows}
    assert v7[callable_bond.values["14"]]["44"] == "I" and v7[callable_bond.values["14"]]["116"] == "1"


def test_v8_data_written_as_v7_is_downgraded(fixture_bytes):
    doc = read_tpt(fixture_bytes("tpt_v8_sample.xlsx"), "v8.xlsx")
    doc.rows[0].values.update({"56": "e2", "48": "2", "150": "1"})
    xml = convert_tpt_to_fundsxml(doc).xml
    v7 = extract_tpt(parse_fundsxml(xml), "V7")
    assert v7.rows[0]["56"] == "e" and v7.rows[0]["48"] == "9"
    assert not any({"150", "151"} & set(r) for r in v7.rows)
    assert v7.rows[0]["1000"] == "V7.0 (official) dated 25 November 2024"
    (issue,) = [i for i in v7.issues if i.code == "v7_downgrade"]
    assert issue.params["n"] >= 3 and "56_Securitisation" in issue.params["fields"]
    v8 = extract_tpt(parse_fundsxml(xml), "V8")
    assert (v8.rows[0]["56"], v8.rows[0]["48"], v8.rows[0]["150"]) == ("e2", "2", "1")
    assert not [i for i in v8.issues if i.code in ("v7_downgrade", "v8_not_applicable_dropped")]


def test_portfolio_is_written_under_the_share_class(fixture_bytes):
    from lxml import etree

    doc = read_tpt(fixture_bytes("12_multi_fund_clean.xlsx"), "multi.xlsx")
    root = etree.fromstring(convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=False)).xml)
    funds = root.findall("Funds/Fund")
    assert len(funds) == len({(r.get("1"), r.get("6")) for r in doc.rows})
    for fund in funds:
        assert fund.find("FundDynamicData") is None
        assert fund.find("Identifiers/ISIN") is None
        (share_class,) = fund.findall("SingleFund/ShareClasses/ShareClass")
        assert share_class.find("Portfolios/Portfolio/Positions/Position") is not None
        assert share_class.findtext("Identifiers/ISIN")


def test_output_version_can_be_chosen(fixture_bytes):
    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    xml = convert_tpt_to_fundsxml(doc).xml
    assert extract_tpt(parse_fundsxml(xml), "V8").version == "V8"


def test_v8_mandatory_issuer_fields_are_checked(fixture_bytes):
    """47/48/50/51 are mandatory for every CIC in V8 (conditional in V7)."""
    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    for row in doc.rows:
        for key in ("47", "48", "50", "51"):
            row.values.pop(key, None)
    xml = convert_tpt_to_fundsxml(doc).xml
    v7_missing = {
        i.field for i in extract_tpt(parse_fundsxml(xml), "V7").issues if i.code == "mandatory_missing"
    }
    v8_missing = {
        i.field for i in extract_tpt(parse_fundsxml(xml), "V8").issues if i.code == "mandatory_missing"
    }
    assert "47" in v8_missing and "50" in v8_missing
    assert not {"47", "48", "50", "51"} & v7_missing


def test_core_only_fundsxml_without_custom_attributes(fixture_bytes):
    """A third-party FundsXML (core structures only) still yields a TPT."""
    from lxml import etree

    xml = convert_tpt_to_fundsxml(
        read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx"), ConvertOptions(include_block=False)
    ).xml
    root = etree.fromstring(xml)
    for ca in root.iter("CustomAttributes"):
        ca.getparent().remove(ca)
    rows = extract_tpt(root).rows
    assert len(rows) == 20
    first = rows[0]
    for key in ("1", "2", "3", "4", "5", "6", "12", "14", "15", "17", "21", "24", "26"):
        assert first.get(key), key


@pytest.mark.parametrize("block", [True, False])
def test_values_real_files_carry_survive(fixture_bytes, block):
    """Cases from real TPT files that a schema-shaped FundsXML cannot hold as they are."""
    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    rows = [r.values for r in doc.rows]
    rows[0]["56"] = "A"  # the schema code list is lower case
    rows[1]["131"] = "l"
    rows[2]["22"] = "9599000.00"  # one currency, yet two different market values
    rows[3]["19"] = ""  # a bond's quantity without nominal: it stands in for Bond/Nominal
    # two holdings of one instrument (one master data entry) in different currencies
    rows[5].update({k: rows[4][k] for k in ("12", "14", "15", "17")})
    rows[5]["21"] = "USD"
    result = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block))
    assert _diffs(doc, extract_tpt(parse_fundsxml(result.xml)).rows) == []


@pytest.mark.parametrize("kind", sorted(POSITION_ELEMENT))
def test_asset_type_without_cic_comes_back(kind):
    """A FundsXML without CIC: the CIC guessed for TPT gives the same AssetType back."""
    cic = ASSET_TYPE.from_xml(kind, {})
    assert ASSET_TYPE.to_xml(cic, {"12": cic, "18": "" if kind == "FE" else "1"})[0] == kind


def test_zero_coupon_type_comes_back():
    """TPT has no zero-coupon type: zero reads as Fixed, and Fixed with a 0 % coupon is zero again."""
    assert RATE_TYPE.from_xml("zero", {}) == "Fixed"
    assert RATE_TYPE.to_xml("Fixed", {"33": "0"}) == ("zero", True)
    assert RATE_TYPE.to_xml("Fixed", {"33": "2.5"}) == ("fix", True)
    assert RATE_TYPE.to_xml("Fixed", {}) == ("fix", True)
    assert ZERO_COUPON_RATE.from_xml("zero", {}) == "0"
    assert ZERO_COUPON_RATE.from_xml("fix", {}) is None


def test_one_isin_in_two_currencies_is_two_assets(fixture_bytes):
    """An instrument listed in two currencies keeps both asset currencies."""
    from lxml import etree

    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    rows = [r.values for r in doc.rows]
    rows[5].update({k: rows[4][k] for k in ("12", "14", "15", "17")})
    rows[5]["21"] = "USD" if rows[4]["21"] != "USD" else "HKD"
    root = etree.fromstring(convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=False)).xml)
    currencies = {
        a.findtext("Currency")
        for a in root.iterfind("AssetMasterData/Asset")
        if a.findtext("Identifiers/ISIN") == rows[4]["14"]
    }
    assert currencies == {rows[4]["21"], rows[5]["21"]}


@pytest.mark.parametrize("block", [True, False])
def test_rows_without_quantity_stay_schema_valid(fixture_bytes, block):
    """ "Other" (x09) without quantity is a fee, private equity without one PrivateEquity, an asset
    without name an empty Name: no mandatory child is left missing."""
    from lxml import etree

    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "v7.xlsx")
    rows = [r.values for r in doc.rows]
    for row, cic, ident in ((rows[1], "XT09", "FEE1"), (rows[2], "XT34", "PE1"), (rows[3], "XT09", "NONAME")):
        row.update({"12": cic, "14": ident, "15": "99", "18": "", "19": ""})
    rows[3]["17"] = ""
    result = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block))
    assert result.valid, result.validation_errors[:3]
    root = etree.fromstring(result.xml)
    kinds = {
        p.findtext("Identifiers/OtherID"): {etree.QName(c).localname for c in p} & {"Fee", "PrivateEquity"}
        for p in root.iterfind(".//Portfolios/Portfolio/Positions/Position")
    }
    assert (kinds["FEE1"], kinds["PE1"]) == ({"Fee"}, {"PrivateEquity"})
    assert _diffs(doc, extract_tpt(parse_fundsxml(result.xml)).rows) == []


def test_quantity_is_read_whatever_the_cic(fixture_bytes):
    """An equity whose supplier gave it a bond CIC: Units and market value still reach TPT, and the
    bond written back is valid (the quantity stands in for the nominal)."""
    doc = read_tpt(fixture_bytes("tpt_all_cic.xlsx"), "all.xlsx")
    row = next(r.values for r in doc.rows if r.values.get("12", "")[2:3] == "3" and r.values.get("18"))
    xml = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=False)).xml
    xml = xml.replace(f"<Value>{row['12']}</Value>".encode(), b"<Value>XT21</Value>")
    back = next(r for r in extract_tpt(parse_fundsxml(xml)).rows if r.get("14") == row["14"])
    assert back["12"] == "XT21"
    assert _same(back["18"], row["18"])
    assert back.get("25") and back.get("23")
    doc.rows[[r.values for r in doc.rows].index(row)].values.update({"12": "XT21"})
    again = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=False))
    assert again.valid, again.validation_errors[:3]
