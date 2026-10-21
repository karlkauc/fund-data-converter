"""Values FundsXML only implies (app.convert.derive)."""

from __future__ import annotations

from decimal import Decimal

from app.convert.derive import complete_portfolio, complete_position, underlying_asset_category


def _row(**kw: str) -> dict[str, str]:
    return {"4": "EUR", "21": "EUR", **{k.removeprefix("f"): v for k, v in kw.items()}}


def test_bond_clean_value_without_accrued_interest():
    row = _row(f12="XT21", f22="1030", f24="1030", f126="30", f26="0.1")
    complete_position(row, None, None)
    assert (row["25"], row["23"], row["125"]) == ("1000", "1000", "30")
    assert (row["27"], row["28"], row["30"]) == ("1030", "1030", "0.1")
    assert row["131"] == "2"


def test_bond_without_interest_amount_has_no_clean_value():
    row = _row(f12="XT21", f22="1030", f24="1030")
    complete_position(row, None, None)
    assert "25" not in row and "23" not in row


def test_equity_in_other_currency():
    row = _row(f12="XT31", f21="USD", f22="200", f24="180")
    complete_position(row, None, Decimal("0.9"))
    assert (row["25"], row["23"]) == ("180", "200")
    assert row["131"] == "3X"
    assert underlying_asset_category("DE31") == "3L"


def test_derivative_exposure_and_weight():
    rows = [
        _row(f12="DEA1", f22="50", f24="50", f26="0.05"),
        _row(f12="XT31", f22="950", f24="950", f26="0.95"),
    ]
    complete_position(rows[0], Decimal("-2000"), Decimal(1))
    complete_position(rows[1], None, Decimal(1))
    complete_portfolio(rows)
    assert (rows[0]["28"], rows[0]["27"], rows[0]["30"]) == ("-2000", "-2000", "-2")
    assert rows[1]["30"] == "0.95"


def test_code_types_and_scr_flag():
    rows = [_row(f12="XT31", f47="529900T8BM49AURSDO55", f48="1")]
    complete_position(rows[0], None, None)
    complete_portfolio(rows)
    assert (rows[0]["48"], rows[0]["51"], rows[0]["116"], rows[0]["120"], rows[0]["11"]) == (
        "1",
        "9",
        "9",
        "9",
        "N",
    )


def test_existing_values_are_kept():
    row = _row(f12="XT31", f22="10", f24="10", f25="9", f27="7", f131="4", f11="Y")
    complete_position(row, None, None)
    complete_portfolio([row])
    assert (row["25"], row["27"], row["131"], row["11"]) == ("9", "7", "4", "Y")


def test_clean_value_in_quotation_currency_gives_the_portfolio_currency_one():
    row = _row(f12="XT21", f21="EUR", f4="CZK", f22="100", f23="98", f24="2435")
    complete_position(row, None, Decimal("24.35"))
    assert row["25"] == "2386.3"


def test_shares_and_cash_ratio_of_the_portfolio():
    rows = [
        _row(f5="1000", f8="12.5", f12="XT72", f24="50"),
        _row(f5="1000", f8="12.5", f12="XT73", f24="-10"),
        _row(f5="1000", f8="12.5", f12="XT31", f24="960"),
    ]
    complete_portfolio(rows)
    assert {r["8b"] for r in rows} == {"80"}
    assert {r["9"] for r in rows} == {"0.04"}


def test_cash_ratio_from_the_weights_of_a_repeated_fund_portfolio():
    # Share class net assets 100 of a fund of 1000: the weights still give the fund's cash ratio.
    rows = [
        _row(f5="100", f12="XT72", f24="50", f26="0.05"),
        _row(f5="100", f12="XT31", f24="950", f26="0.95"),
    ]
    complete_portfolio(rows)
    assert {r["9"] for r in rows} == {"0.05"}


def test_cash_ratio_without_cash_and_existing_values_kept():
    rows = [_row(f5="1000", f8="3", f12="XT31", f24="1000")]
    complete_portfolio(rows)
    assert (rows[0]["8b"], rows[0]["9"]) == ("333.333333", "0")
    kept = [_row(f5="1000", f8="3", f8b="300", f9="0.1", f12="XT72", f24="500")]
    complete_portfolio(kept)
    assert (kept[0]["8b"], kept[0]["9"]) == ("300", "0.1")


def test_issuer_names_from_the_instrument_name():
    row = _row(f12="XT72", f17="Konto EUR", f24="10")
    complete_position(row, None, None)
    assert (row["46"], row["49"]) == ("Konto EUR", "Konto EUR")
    issued = _row(f12="DE21", f17="Bund 2030", f46="Bundesrepublik", f24="10")
    complete_position(issued, None, None)
    assert (issued["46"], issued["49"]) == ("Bundesrepublik", "Bundesrepublik")
    grouped = _row(f12="DE21", f17="Bund 2030", f46="KfW", f49="Bundesrepublik", f24="10")
    complete_position(grouped, None, None)
    assert (grouped["46"], grouped["49"]) == ("KfW", "Bundesrepublik")
