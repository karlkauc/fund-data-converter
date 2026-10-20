"""FundsXML → TPT reports share classes: field 1 is the share class ISIN, never the fund's."""

from __future__ import annotations

from app.convert.to_tpt import extract_tpt
from app.ingest.fundsxml_reader import parse_fundsxml


def _portfolio(*positions: tuple[str, dict[str, str]], date: str = "2026-09-30") -> str:
    out = []
    for isin, amounts in positions:
        values = "".join(f'<Amount ccy="{c}">{v}</Amount>' for c, v in amounts.items())
        out.append(
            f"<Position><UniqueID>{isin}</UniqueID><Identifiers><ISIN>{isin}</ISIN></Identifiers>"
            f"<Currency>EUR</Currency><TotalValue>{values}</TotalValue>"
            "<TotalPercentage>50</TotalPercentage></Position>"
        )
    return _wrap("".join(out), date)


def _wrap(positions: str, date: str = "2026-09-30") -> str:
    return (
        f"<Portfolios><Portfolio><NavDate>{date}</NavDate>"
        f"<Positions>{positions}</Positions></Portfolio></Portfolios>"
    )


def _share_class(isin: str, ccy: str, price: str, nav: dict[str, str], portfolio: str = "") -> str:
    amounts = "".join(f'<Amount ccy="{c}">{v}</Amount>' for c, v in nav.items())
    return (
        f"<ShareClass><Identifiers><ISIN>{isin}</ISIN></Identifiers>"
        f"<Names><OfficialName>Class {isin}</OfficialName></Names><Currency>{ccy}</Currency>"
        f"<Prices><Price><ActionCode>C</ActionCode><NavDate>2026-09-30</NavDate><PriceCurrency>{ccy}</PriceCurrency>"
        f"<PriceNature>OFFICIAL</PriceNature><NavPrice>{price}</NavPrice></Price></Prices>"
        f"<TotalAssetValues><TotalAssetValue><NavDate>2026-09-30</NavDate><TotalAssetNature>OFFICIAL</TotalAssetNature>"
        f"<TotalNetAssetValue>{amounts}</TotalNetAssetValue><SharesOutstanding>1000</SharesOutstanding>"
        f"</TotalAssetValue></TotalAssetValues>{portfolio}</ShareClass>"
    )


def _doc(share_classes: list[str], fund_portfolio: str = "", fund_ccy: str = "EUR") -> bytes:
    dynamic = (
        "<FundDynamicData><TotalAssetValues><TotalAssetValue><NavDate>2026-09-30</NavDate>"
        '<TotalAssetNature>OFFICIAL</TotalAssetNature><TotalNetAssetValue><Amount ccy="EUR">9999</Amount>'
        f"</TotalNetAssetValue></TotalAssetValue></TotalAssetValues>{fund_portfolio}</FundDynamicData>"
    )
    return (
        "<FundsXML4><ControlData/><Funds><Fund><Identifiers><ISIN>LU0000000FND</ISIN><LEI>FUNDLEI</LEI></Identifiers>"
        f"<Names><OfficialName>Umbrella</OfficialName></Names><Currency>{fund_ccy}</Currency>"
        f"<SingleFundFlag>true</SingleFundFlag>{dynamic}"
        f"<SingleFund><ShareClasses>{''.join(share_classes)}</ShareClasses></SingleFund></Fund></Funds>"
        "</FundsXML4>"
    ).encode()


def _by_portfolio(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        out.setdefault(r["1"], []).append(r)
    return out


FUND_PF = _portfolio(("DE0001102580", {"EUR": "100"}), ("DE0001102598", {"EUR": "300"}))
OWN_PF = _portfolio(("AT0000A0K2C4", {"EUR": "77"}))


def test_fund_portfolio_is_repeated_per_share_class():
    xml = _doc(
        [
            _share_class("AT0000000AA1", "EUR", "101.5", {"EUR": "5000"}),
            _share_class("AT0000000BB2", "EUR", "98.2", {"EUR": "4999"}),
        ],
        FUND_PF,
    )
    extract = extract_tpt(parse_fundsxml(xml), "V7")
    by_pf = _by_portfolio(extract.rows)
    assert set(by_pf) == {"AT0000000AA1", "AT0000000BB2"}
    a = by_pf["AT0000000AA1"]
    assert [r["14"] for r in a] == ["DE0001102580", "DE0001102598"]
    assert (a[0]["2"], a[0]["3"], a[0]["4"], a[0]["5"], a[0]["8"], a[0]["8b"]) == (
        "1",
        "Class AT0000000AA1",
        "EUR",
        "5000",
        "101.5",
        "1000",
    )
    assert by_pf["AT0000000BB2"][0]["5"] == "4999"
    assert extract.stats["portfolios"] == 2


def test_own_share_class_portfolio_wins():
    xml = _doc(
        [
            _share_class("AT0000000AA1", "EUR", "101.5", {"EUR": "5000"}, OWN_PF),
            _share_class("AT0000000BB2", "EUR", "98.2", {"EUR": "4999"}),
        ],
        FUND_PF,
    )
    by_pf = _by_portfolio(extract_tpt(parse_fundsxml(xml), "V7").rows)
    assert [r["14"] for r in by_pf["AT0000000AA1"]] == ["AT0000A0K2C4"]
    assert [r["14"] for r in by_pf["AT0000000BB2"]] == ["DE0001102580", "DE0001102598"]
    assert "LU0000000FND" not in by_pf


def test_share_class_without_any_portfolio_is_skipped():
    xml = _doc(
        [
            _share_class("AT0000000AA1", "EUR", "101.5", {"EUR": "5000"}, OWN_PF),
            _share_class("AT0000000BB2", "EUR", "98.2", {"EUR": "4999"}),
        ]
    )
    extract = extract_tpt(parse_fundsxml(xml), "V8")
    assert set(_by_portfolio(extract.rows)) == {"AT0000000AA1"}
    skipped = [i for i in extract.issues if i.code == "shareclass_no_portfolio"]
    assert [i.params["shareclass"] for i in skipped] == ["AT0000000BB2"]


def test_market_value_in_share_class_currency():
    xml = _doc(
        [
            _share_class("IE0000000US1", "USD", "10", {"USD": "1200", "EUR": "1000"}),
            _share_class("IE0000000EU1", "EUR", "10", {"EUR": "4000"}),
        ],
        _portfolio(("DE0001102580", {"EUR": "100"}), ("DE0001102598", {"EUR": "300", "USD": "350"})),
    )
    extract = extract_tpt(parse_fundsxml(xml), "V7")
    by_pf = _by_portfolio(extract.rows)
    usd = by_pf["IE0000000US1"]
    assert usd[0]["4"] == "USD"
    assert usd[0]["24"] == "120"  # converted at the NAV rate 1200 / 1000
    assert usd[1]["24"] == "350"  # reported amount wins
    assert [r["24"] for r in by_pf["IE0000000EU1"]] == ["100", "300"]
    assert [i.code for i in extract.issues if i.code.startswith("fx_")] == ["fx_derived"]


def test_share_class_without_net_assets_is_skipped():
    xml = _doc(
        [
            _share_class("AT0000000AA1", "EUR", "101.5", {"EUR": "5000"}),
            _share_class("AT0000000ZZ0", "EUR", "100", {"EUR": "0"}),
        ],
        FUND_PF,
    )
    extract = extract_tpt(parse_fundsxml(xml), "V7")
    assert set(_by_portfolio(extract.rows)) == {"AT0000000AA1"}
    assert [i.params["shareclass"] for i in extract.issues if i.code == "shareclass_inactive"] == [
        "AT0000000ZZ0"
    ]


def test_quotation_currency_value_from_units_and_price():
    position = (
        "<Position><UniqueID>INE117A01022</UniqueID><Identifiers><ISIN>INE117A01022</ISIN></Identifiers>"
        '<Currency>INR</Currency><TotalValue><Amount ccy="EUR">500</Amount></TotalValue>'
        '<TotalPercentage>50</TotalPercentage><Equity><Units>10</Units><Price><Amount ccy="INR">4800</Amount>'
        "</Price></Equity></Position>"
    )
    xml = _doc([_share_class("AT0000000AA1", "EUR", "1", {"EUR": "1000"})], _wrap(position))
    (row,) = extract_tpt(parse_fundsxml(xml), "V7").rows
    assert (row["21"], row["22"], row["24"]) == ("INR", "48000", "500")


def test_fund_without_share_classes_stays_on_fund_level():
    xml = _doc([], FUND_PF)
    rows = extract_tpt(parse_fundsxml(xml), "V7").rows
    assert {r["1"] for r in rows} == {"LU0000000FND"}
    assert rows[0]["5"] == "9999"


def test_rate_from_the_positions_when_the_share_class_nav_has_one_currency():
    position = (
        "<Position><UniqueID>US0000000001</UniqueID><Identifiers><ISIN>US0000000001</ISIN></Identifiers>"
        '<Currency>USD</Currency><TotalValue><Amount ccy="HUF">3500</Amount><Amount ccy="USD">10</Amount>'
        "</TotalValue><TotalPercentage>100</TotalPercentage>"
        '<FXRates><FXRate fromCcy="EUR" toCcy="HUF" mulDiv="M">350</FXRate></FXRates>'
        "<Equity><Units>1</Units></Equity></Position>"
    )
    xml = _doc([_share_class("HU0000000EU1", "EUR", "1", {"EUR": "10"})], _wrap(position), "HUF")
    extract = extract_tpt(parse_fundsxml(xml), "V7")
    (row,) = extract.rows
    assert (row["4"], row["24"], row["22"]) == ("EUR", "10", "10")
    assert [i.code for i in extract.issues if i.code.startswith("fx_")] == ["fx_derived"]


def test_reporting_date_is_not_before_the_valuation_date():
    xml = _doc([_share_class("AT0000000AA1", "EUR", "101.5", {"EUR": "5000"})], FUND_PF)
    early = xml.replace(
        b"<ControlData/>", b"<ControlData><ContentDate>2026-09-01</ContentDate></ControlData>"
    )
    late = xml.replace(b"<ControlData/>", b"<ControlData><ContentDate>2026-10-02</ContentDate></ControlData>")
    assert extract_tpt(parse_fundsxml(early), "V7").rows[0]["7"] == "2026-09-30"
    assert extract_tpt(parse_fundsxml(late), "V7").rows[0]["7"] == "2026-10-02"


def test_unique_id_when_the_asset_has_no_identifier():
    def position(key: str, identifiers: str) -> str:
        return (
            f"<Position><UniqueID>{key}</UniqueID><Identifiers>{identifiers}</Identifiers>"
            '<Currency>EUR</Currency><TotalValue><Amount ccy="EUR">10</Amount></TotalValue>'
            "<TotalPercentage>1</TotalPercentage></Position>"
        )

    positions = position("OT51304", '<OtherID FreeType="InternalCode"/>') + position(
        "P2", "<ISIN>DE0001102580</ISIN>"
    )
    xml = _doc([_share_class("AT0000000AA1", "EUR", "1", {"EUR": "1000"})], _wrap(positions))
    rows = extract_tpt(parse_fundsxml(xml), "V7").rows
    assert [(r["14"], r["15"]) for r in rows] == [("OT51304", "99"), ("DE0001102580", "1")]
