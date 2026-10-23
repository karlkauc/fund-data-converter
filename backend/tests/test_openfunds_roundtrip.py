"""openfunds ⇄ FundsXML, and TPT ⇄ openfunds through FundsXML, must give back every value.

Values the target leaves empty may come back filled where FundsXML implies them (a share class
name taken from the fund name, holding amounts derived by the TPT extraction).
"""

from __future__ import annotations

import re

import pytest
from test_roundtrip import FILES, _diffs, _same

from app.convert.fundsxml_to_openfunds import extract_openfunds
from app.convert.openfunds_to_fundsxml import OfConvertOptions, convert_openfunds_to_fundsxml
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml
from app.convert.to_tpt import extract_tpt
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.openfunds_reader import read_openfunds
from app.ingest.tpt_reader import read_tpt
from app.mapping.openfunds_holdings import add_accrued_interest, holding_to_tpt, tpt_to_holding
from app.mapping.openfunds_rules import DEFAULTS, OF_FUND, STATIC_RULES
from app.mapping.openfunds_templates import templates
from app.model.xmltree import parse_decimal
from app.schema.model import fundsxml_model
from app.spec.openfunds import load_openfunds
from app.writers.openfunds_writer import write_openfunds

SHARECLASS = {
    "OFST020000": "LU0000000001",
    "OFST010020": "Demo Fund - Bonds",
    "OFST010030": "529900T8BM49AURSDO55",
    "OFST010010": "LU",
    "OFST010410": "EUR",
    "OFST001020": "Demo ManCo S.A.",
    "OFST020060": "Demo Fund - Bonds A EUR",
    "OFST020540": "EUR",
    "OFST020050": "A",
    "OFST020400": "distributing",
    "OFST020560": "2020-01-15",
    "OFST6030AT": "yes",
    "OFST452010": "0.015",
    "OFST452200": "0.00808",
    "OFST452220": "2025-02-15",
    "OFST010580": "no",
    "OFST010720": "yes",
    "OFST6030DE": "no",  # with a deregistration date: De-registered
    "OFST6011DE": "2024-06-30",
    "OFDY000035": "101.5",
    "OFDY000036": "2025-12-31",
    "OFDY000070": "1000000",
    "OFDY000071": "2025-12-31",
    "OFST024000": "3",  # revoked: custom attribute
    "OFST500010": "yes",  # no FundsXML counterpart: custom attribute
    "OFEM000010": "v4.3",  # incomplete EMT: custom attribute
    "My Rating": "A",  # non-openfunds column
}
SECOND = {
    "OFST020000": "LU0000000002",
    "OFST010020": "Demo Fund - Bonds",
    "OFST010030": "529900T8BM49AURSDO55",
    "OFST010010": "DE",  # differs from the fund's first share class
    "OFST020540": "USD",
    "OFST020261": "yes, full NAV hedge",
}
HOLDINGS = [
    {
        "OFST020000": "LU0000000001",
        "OFPH000010": "2025-12-31",
        "OFPH000100": "DE0001102580",
        "OFPH000110": "110258",  # second identifier: custom attribute
        "OFPH000200": "Bund 2030",
        "OFPH000215": "DE21",
        "OFPH000250": "500000",
        "OFPH000300": "0.5",
        "OFPH000400": "EUR",
        "OFPH000460": "0.025",
        "OFPH000470": "480000",
        "OFPH000625": "annually",
        "OFPH000640": "Call",
    },
    {
        "OFST020000": "LU0000000001",
        "OFPH000010": "2025-12-31",
        "OFPH000190": "CASH1",
        "OFPH000195": "Internal",
        "OFPH000200": "Cash EUR",
        "OFPH000215": "XT71",
        "OFPH000250": "500000",
        "OFPH000300": "0.5",
        "OFPH000400": "EUR",
        "OFPH000745": "no",  # no TPT counterpart: custom attribute
    },
]


def _lost(original: dict[str, str], back: dict[str, str]) -> dict[str, tuple[str, str | None]]:
    return {k: (v, back.get(k)) for k, v in original.items() if not _same(v, back.get(k, ""))}


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_openfunds_roundtrip(fmt):
    data, filename, _ = write_openfunds([SHARECLASS, SECOND], HOLDINGS, fmt)
    result = convert_openfunds_to_fundsxml(read_openfunds(data, filename))
    assert result.valid, result.validation_errors[:5]
    back = extract_openfunds(parse_fundsxml(result.xml))
    assert [_lost(o, b) for o, b in zip([SHARECLASS, SECOND], back.shareclasses, strict=True)] == [{}, {}]
    assert [_lost(o, b) for o, b in zip(HOLDINGS, back.holdings, strict=True)] == [{}, {}]
    codes = {i.code for i in result.issues}
    assert {"of_fund_value_differs", "of_template_incomplete", "of_revoked_field"} <= codes


def test_values_reach_the_core_structures():
    data, filename, _ = write_openfunds([SHARECLASS], HOLDINGS)
    result = convert_openfunds_to_fundsxml(read_openfunds(data, filename))
    root = parse_fundsxml(result.xml)
    sc = root.find("Funds/Fund/SingleFund/ShareClasses/ShareClass")
    assert sc.findtext("Identifiers/ISIN") == "LU0000000001"
    assert sc.findtext("ShareClassType/EarningUse") == "D"
    assert sc.findtext("Prices/Price/NavPrice") == "101.5"
    fund = root.find("Funds/Fund")
    assert fund.findtext("FundStaticData/OngoingCosts/OngoingCost/Percentage") == "0.808"
    assert fund.findtext("SingleFund/SingleFundStaticData/ManagementType") == "PASSIVE"
    reg = sc.find("RegistrationCountries/RegistrationCountry[CountryCode='DE']")
    assert reg.findtext("Status") == "De-registered" and reg.findtext("StatusDate") == "2024-06-30"
    assert root.findtext("Funds/Fund/FundStaticData/InvestmentCompany/Name") == "Demo ManCo S.A."
    positions = sc.findall("Portfolios/Portfolio/Positions/Position")
    assert len(positions) == 2
    assert positions[0].findtext("Bond/Nominal") == "480000"
    names = {a.findtext("Name") for a in sc.iterfind("CustomAttributes/Attribute")}
    assert {"OF_OFST024000", "OF_OFST500010", "OF_My Rating"} <= names
    assert "OF_OFST020000" not in names


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("block", [True, False])
def test_tpt_through_openfunds_is_lossless(fixture_bytes, name, block):
    doc = read_tpt(fixture_bytes(name), name)
    fx = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block))
    extract = extract_openfunds(parse_fundsxml(fx.xml))
    data, filename, _ = write_openfunds(extract.shareclasses, extract.holdings)
    back = convert_openfunds_to_fundsxml(read_openfunds(data, filename))
    rows = extract_tpt(parse_fundsxml(back.xml)).rows
    assert _diffs(doc, rows) == []


def test_tpt_columns_only_with_tpt_origin(fixture_bytes):
    """A pure openfunds document gets no TPT_ columns; a converted TPT file does."""
    data, filename, _ = write_openfunds([SHARECLASS], HOLDINGS)
    pure = extract_openfunds(
        parse_fundsxml(convert_openfunds_to_fundsxml(read_openfunds(data, filename)).xml)
    )
    assert not any(k.startswith("TPT_") for h in pure.holdings for k in h)
    doc = read_tpt(fixture_bytes("tpt_v7_sample.xlsx"), "x.xlsx")
    tpt = extract_openfunds(parse_fundsxml(convert_tpt_to_fundsxml(doc).xml))
    assert any(k.startswith("TPT_") for k in tpt.holdings[0])
    plain = extract_openfunds(parse_fundsxml(convert_tpt_to_fundsxml(doc).xml), non_openfunds_columns=False)
    assert not any(k.startswith("TPT_") for h in plain.holdings for k in h)


def test_holding_adapter():
    tpt, represented = holding_to_tpt(HOLDINGS[0])
    assert tpt["14"] == "DE0001102580" and tpt["15"] == "1"
    assert tpt["38"] == "1" and tpt["42"] == "Cal"
    assert "OFPH000110" not in represented  # only one instrument identifier fits TPT
    values, kept = tpt_to_holding({"14": "X1", "15": "99", "44": "B", "52": "CZ", "58": "Y"})
    assert values == {
        "OFPH000190": "X1",
        "OFPH000195": "Internal",
        "OFPH000650": "bearer",
        "OFPH000712": "CZ",  # no TPT reference in openfunds: EXTRA_PAIRS
        "OFPH000715": "yes",
    }
    assert kept == {"14", "15", "44", "52", "58"}


def test_fund_cic_travels_as_ept_fund_cic_code():
    """TPT 123 (the fund's CIC) has no openfunds column but OFEP000900; alone it makes no EPT record."""
    data, filename, _ = write_openfunds([{**SECOND, "OFEP000900": "XL41"}], [])
    result = convert_openfunds_to_fundsxml(read_openfunds(data, filename))
    root = parse_fundsxml(result.xml)
    cic = "Funds/Fund/FundStaticData/Classifications/Classification[ListedGroup='CIC']/Value"
    assert root.findtext(cic) == "XL41"
    assert "of_template_incomplete" not in {i.code for i in result.issues}
    assert extract_openfunds(root).shareclasses[0]["OFEP000900"] == "XL41"


def test_accrued_interest_from_market_values():
    """openfunds has no accrued interest column: market value (24) minus clean value (25) is TPT 126."""
    bond = {"12": "DE21", "24": "1675506.23", "25": "1630080.00"}
    add_accrued_interest(bond)
    assert bond["126"] == "45426.23"
    zero_coupon = {"12": "DE21", "24": "1000", "25": "1000"}
    add_accrued_interest(zero_coupon)
    assert zero_coupon["126"] == "0"
    given = {"12": "DE21", "24": "10", "25": "8", "126": "1.5"}
    add_accrued_interest(given)
    assert given["126"] == "1.5"
    equity = {"12": "DE31", "24": "10", "25": "8"}
    add_accrued_interest(equity)
    assert "126" not in equity
    # In a foreign currency the quotation-currency amounts follow from 22/24.
    foreign = {"12": "US21", "4": "EUR", "21": "USD", "22": "1100", "24": "1000", "25": "900"}
    add_accrued_interest(foreign)
    assert (foreign["126"], foreign["125"], foreign["23"]) == ("100", "110", "990")
    domestic = {"12": "DE21", "4": "EUR", "21": "EUR", "22": "1000", "24": "1000", "25": "900"}
    add_accrued_interest(domestic)
    assert "125" not in domestic and "23" not in domestic
    # Not rounded to cents: the amounts keep the places of the source.
    exact = {"12": "CH21", "4": "EUR", "21": "CHF", "22": "1482000.1234567"}
    exact |= {"24": "1500000.5", "25": "1476919.2212895"}
    add_accrued_interest(exact)
    assert exact["126"] == "23081.2787105"
    assert parse_decimal(exact["23"]) + parse_decimal(exact["125"]) == parse_decimal(exact["22"])
    assert len(exact["125"].split(".")[1]) == 7


def test_accrued_interest_reaches_fundsxml():
    holding = {**HOLDINGS[0], "OFPH000250": "500450", "OFPH000260": "500000"}
    data, filename, _ = write_openfunds([SHARECLASS], [holding])
    root = parse_fundsxml(convert_openfunds_to_fundsxml(read_openfunds(data, filename)).xml)
    pos = root.find("Funds/Fund/SingleFund/ShareClasses/ShareClass/Portfolios/Portfolio/Positions/Position")
    assert pos.findtext("Bond/InterestClaimGross/Amount") == "450"


# -- mapping tables ---------------------------------------------------------------


def _schema_path(path: str) -> list[str]:
    steps = [re.sub(r"\[[^]]*\]", "", s) for s in re.split(r"/(?![^\[]*\])", path)]
    return [s for s in steps if s and not s.startswith("@")]


def test_static_rules_point_into_the_schema():
    model = fundsxml_model()
    catalog = load_openfunds()
    base = {OF_FUND: ["Funds", "Fund"]}
    sc_base = ["Funds", "Fund", "SingleFund", "ShareClasses", "ShareClass"]
    for rule in STATIC_RULES:
        match = catalog.match_header(rule.field)
        assert match and match.of_id in catalog.by_id, rule.field
        path = base.get(rule.ctx, sc_base) + _schema_path(rule.path)
        assert model.decl_at(path) is not None, (rule.field, rule.path)
    for ctx, parent, child, _ in DEFAULTS:
        path = base.get(ctx, sc_base) + _schema_path(f"{parent}/{child}")
        assert model.decl_at(path) is not None, (parent, child)


def test_template_fields_point_into_the_schema():
    model = fundsxml_model()
    catalog = load_openfunds()
    counts = {}
    for tpl in templates():
        counts[tpl.name] = len(tpl.fields)
        for f in tpl.fields:
            assert catalog.by_id[f.of_id].ref(tpl.name), f.of_id
            path = tpl.record.split("/") + _schema_path(f.path)
            assert model.decl_at(path) is not None, (f.of_id, f.path)
    assert counts["EET"] >= 600 and counts["EMT"] >= 100 and counts["EPT"] >= 130 and counts["EFT"] >= 20


def test_template_values():
    tpl = {t.name: t for t in templates()}
    emt = {f.of_id: f for f in tpl["EMT"].fields}
    assert emt["OFEM000010"].to_xml("v4.3") == ["V4S3"] and emt["OFEM000010"].lossless("v4.3")
    yes_no = next(f for f in tpl["EPT"].fields if "YES" in f.enums)
    assert yes_no.to_xml("yes") == ["YES"] and yes_no.from_xml(["NO"]) == "no"
    pct = next(f for f in tpl["EET"].fields if f.percent)
    assert pct.to_xml("0.25") == ["25"] and pct.lossless("0.25")
    many = next(f for f in tpl["EET"].fields if f.many and not f.enums)
    assert many.to_xml("GB;DE") == ["GB", "DE"] and many.from_xml(["GB", "DE"]) == "GB;DE"


@pytest.mark.parametrize(
    "name", ["openfunds_sample.xlsx", "openfunds_multi.xlsx", "openfunds_static.xlsx", "openfunds_csv.zip"]
)
def test_openfunds_samples_are_lossless(fixture_bytes, name):
    doc = read_openfunds(fixture_bytes(name), name)
    result = convert_openfunds_to_fundsxml(doc)
    assert result.valid, result.validation_errors[:5]
    back = extract_openfunds(parse_fundsxml(result.xml))
    for b in back.shareclasses:
        # FundsXML has one NAV date: a number-of-shares date without an AuM date comes back as the latter.
        for nos, aum in (("OFDY000066", "OFDY000061"), ("OFDY000076", "OFDY000071")):
            b.setdefault(nos, b.get(aum, ""))
    assert [_lost(o.values, b) for o, b in zip(doc.shareclasses, back.shareclasses, strict=True)] == [
        {} for _ in doc.shareclasses
    ]
    assert [_lost(o.values, b) for o, b in zip(doc.holdings, back.holdings, strict=True)] == [
        {} for _ in doc.holdings
    ]


@pytest.mark.parametrize("name", ["openfunds_sample.xlsx", "openfunds_multi.xlsx", "tpt_v7_sample.xlsx"])
def test_implied_tpt_attributes_can_be_left_out(fixture_bytes, name):
    """Without the TPT values the FundsXML implies the document is smaller and reads back the same."""
    if name.startswith("tpt"):
        fx = convert_tpt_to_fundsxml(read_tpt(fixture_bytes(name), name), ConvertOptions())
        extract = extract_openfunds(parse_fundsxml(fx.xml))
        data, filename, _ = write_openfunds(extract.shareclasses, extract.holdings)
        of_doc = read_openfunds(data, filename)
    else:
        of_doc = read_openfunds(fixture_bytes(name), name)
    full = convert_openfunds_to_fundsxml(of_doc)
    slim = convert_openfunds_to_fundsxml(of_doc, OfConvertOptions(implied_tpt_attributes=False))
    assert slim.valid, slim.validation_errors[:3]
    assert slim.stats["custom_attributes"] < full.stats["custom_attributes"]
    assert extract_tpt(parse_fundsxml(slim.xml)).rows == extract_tpt(parse_fundsxml(full.xml)).rows
    back_full, back_slim = (extract_openfunds(parse_fundsxml(r.xml)) for r in (full, slim))
    assert back_slim.holdings == back_full.holdings
    assert back_slim.shareclasses == back_full.shareclasses
