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
    result = convert_tpt_to_fundsxml(doc)
    xml = result.xml.decode()
    assert "<TPTVersion>V7.0</TPTVersion>" in xml
    assert "TPT_150_LTEI_Fund_Elligibility" in xml
    rows = extract_tpt(parse_fundsxml(result.xml)).rows
    assert rows[0]["56"] == "e2"
    assert rows[0]["150"] == "0"
    assert rows[0]["1000"].startswith("V8.0")


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
