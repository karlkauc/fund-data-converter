from __future__ import annotations

import pytest

from app.model.xmltree import Node, normalize, parse_decimal, serialize_at
from app.schema.model import SimpleType, fundsxml_model


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1234.5600", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("0,5", "0.5"),
        ("5000000.00", "5000000"),
        ("-0.000", "0"),
        ("1E-5", "0.00001"),
    ],
)
def test_decimals(raw, expected):
    assert normalize(raw, SimpleType("decimal")) == expected


@pytest.mark.parametrize("raw", ["abc", "1%", "nan"])
def test_bad_decimals(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


@pytest.mark.parametrize("raw", ["2025-12-31", "31.12.2025", "31/12/2025", "20251231", "2025-12-31T00:00:00"])
def test_dates(raw):
    assert normalize(raw, SimpleType("date")) == "2025-12-31"


def test_enum_matching():
    st = SimpleType("string", enums=("1", "2", "99"))
    assert normalize("1 - ISIN", st) == "1"
    with pytest.raises(ValueError):
        normalize("42", st)
    assert normalize("bullet", SimpleType("string", enums=("Bullet", "Sinkable"))) == "Bullet"


def test_children_are_ordered_and_optional_branches_pruned():
    model = fundsxml_model()
    pos = Node("Position")
    pos.set("TotalValue/Amount[@ccy=EUR]", "100")
    pos.set("Currency", "EUR")
    pos.set("UniqueID", "A_1")
    pos.set("PricingSource/Listed", "NOT-A-SOURCE", origin="2:99")  # invalid enum in an optional branch
    pos.ensure("Account")
    res = serialize_at(
        model, pos, ["Funds", "Fund", "FundDynamicData", "Portfolios", "Portfolio", "Positions", "Position"]
    )
    assert [c.tag for c in res.element] == ["UniqueID", "Currency", "TotalValue", "Account"]
    assert res.dropped and res.dropped[0].origins == ("2:99",)
    assert not res.invalid


def test_required_content_is_kept_and_reported():
    model = fundsxml_model()
    pos = Node("Position")
    pos.set("UniqueID", "A_1")
    pos.ensure("Bond")  # Bond/Nominal is required
    res = serialize_at(
        model, pos, ["Funds", "Fund", "FundDynamicData", "Portfolios", "Portfolio", "Positions", "Position"]
    )
    assert res.element is not None
    assert any("TotalValue" in d.reason for d in res.invalid)


def test_empty_required_containers_are_created():
    model = fundsxml_model()
    fund = Node("Fund")
    fund.set("Names/OfficialName", "X")
    fund.set("Currency", "EUR")
    fund.set("SingleFundFlag", "true")
    fund.ensure("SingleFund")
    res = serialize_at(model, fund, ["Funds", "Fund"])
    tags = [c.tag for c in res.element]
    assert tags == ["Identifiers", "Names", "Currency", "SingleFundFlag", "SingleFund"]
    assert not res.invalid


def test_quoted_predicate_values_carry_path_characters():
    from app.model.xmltree import Node, _parse, quote_value

    assert quote_value("plain") == "plain"
    assert quote_value("a[1]") == "'a[1]'"
    assert quote_value("O'Brien") == '"O\'Brien"'
    assert _parse(f"List/Item[Name={quote_value('x/y [z]')}]/Value") == (
        ("List", None, None),
        ("Item", "Name", "x/y [z]"),
        ("Value", None, None),
    )
    root = Node("Root")
    root.ensure(f"List/Item[Name={quote_value('a]b')}]/Value").text = "1"
    assert root.find(f"List/Item[Name={quote_value('a]b')}]/Value").text == "1"
