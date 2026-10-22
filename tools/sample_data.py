"""Synthetic TPT data for the bundled example files (see make_samples.py).

Positions are written as ``{TPT field: value}`` with the quotation-currency market value (22) and
the rate QC → PC; ``build_portfolio`` fills the portfolio currency amounts, weights, NAV and the
derived fields with the converter's own derivation (``app.convert.derive``), so the numbers
reconcile. ISINs and LEIs are constructed with valid check digits; the equity, ETF and index ISINs
are real, published ones.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.convert.derive import amount, complete_portfolio, complete_position
from app.model.xmltree import format_decimal
from app.spec.catalog import VERSION_LABELS


def isin(prefix: str) -> str:
    """``prefix`` (11 characters) plus the Luhn check digit."""
    digits = "".join(str(int(c, 36)) for c in prefix)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return prefix + str((10 - total % 10) % 10)


def lei(prefix: str) -> str:
    """``prefix`` (18 characters) plus the ISO 17442 check digits."""
    n = int("".join(str(int(c, 36)) for c in prefix + "00"))
    return f"{prefix}{98 - n % 97:02d}"


VALUATION = "2025-12-31"

CUSTODIAN = ("DEMO CUSTODIAN BANK SA", lei("529900WL9GZRMTQJ4B"), "LU")
MANCO = ("DEMO ASSET MANAGEMENT SA", lei("529900DEMOMANCO0AM"), "DEMO ASSET MANAGEMENT GROUP")

# Issuers: name, LEI (None = no code, 48 = 9), group, country, NACE, counterparty sector (137)
BUND = ("BUNDESREPUBLIK DEUTSCHLAND", lei("529900MBHTLGWCUCVS"), None, "DE", "O8411", "10")
DEMO_CORP = ("DEMO INDUSTRIES SA", None, "DEMO INDUSTRIES GROUP", "FR", "C2410", "1")
SIEMENS = ("SIEMENS ENERGY FINANCE BV", lei("529900DEMOSIEMENS1"), "SIEMENS ENERGY AG", "NL", "K6420", "1")
APPLE = ("APPLE INC", "HWUPKR0MPOU8FGXBT394", None, "US", "C2620", "1")
ASML = ("ASML HOLDING NV", "724500Y6DUVHQD6OXN27", None, "NL", "C2611", "1")
SAP = ("SAP SE", "529900D6BF99LW9R2E68", None, "DE", "J6201", "1")
SHELL = ("SHELL PLC", "21380068P1DRHMJ8KU70", None, "GB", "B0610", "1")
GROWTH = ("DEMO GROWTH PARTNERS II SCSP", None, None, "LU", "K6430", "4")
BLACKROCK = (
    "BLACKROCK ASSET MANAGEMENT IRELAND",
    lei("549300DEMOBLKRCK1E"),
    "BLACKROCK INC",
    "IE",
    "K6430",
    "4",
)
MMF = (
    "DEMO LIQUIDITY FUNDS SICAV",
    lei("529900DEMOLIQUIDTY"),
    "DEMO ASSET MANAGEMENT GROUP",
    "LU",
    "K6430",
    "4",
)
BANK = ("DEMO INVESTMENT BANK AG", lei("529900DEMOINVBANK0"), "DEMO BANKING GROUP", "DE", "K6419", "2")
SPV = ("DEMO AUTO LOANS 2024-1 DAC", lei("635400DEMOAUTOLOAN"), None, "IE", "K6491", "3")
EUREX = ("EUREX CLEARING AG", lei("529900LN3S50JPU47S"), "DEUTSCHE BOERSE AG", "DE", "K6611", "11")
PROPCO = ("DEMO OFFICE PROPCO SARL", None, "DEMO ASSET MANAGEMENT GROUP", "LU", "L6820", "1")
BORROWER = ("DEMO MITTELSTAND GMBH", None, None, "DE", "C2829", "1")
CUSTODIAN_ISSUER = (CUSTODIAN[0], CUSTODIAN[1], "DEMO CUSTODIAN GROUP", "LU", "K6419", "2")

_DEFAULTS = {"106": "9", "107": "LU", "108": "2", "110": "1", "55": "NC", "57": "N"}


def position(cic: str, code: str, code_type: str, name: str, ccy: str, mv_qc: str, issuer, **fields) -> dict:
    """A position; ``fields`` uses ``f<key>`` for TPT field ``<key>`` (``f8b`` → ``8b``)."""
    values = {
        "12": cic,
        "13": "1",
        "14": code,
        "15": code_type,
        "17": name,
        "21": ccy,
        "22": mv_qc,
    }
    i_name, i_lei, group, country, nace, sector = issuer
    values.update(
        {
            "46": i_name,
            "47": i_lei or "",
            "48": "1" if i_lei else "9",
            "49": group or i_name,
            "50": i_lei if i_lei and not group else "",
            "51": "1" if i_lei and not group else "9",
            "52": country,
            "53": "1",
            "54": nace,
            "148": nace,
            "137": sector,
        }
    )
    values.update(_DEFAULTS)
    values.update({k[1:]: str(v) for k, v in fields.items()})
    return {k: v for k, v in values.items() if v != ""}


# -- all CIC categories ----------------------------------------------------------------------

USD_EUR = Decimal("0.92")  # EUR per USD
GBP_EUR = Decimal("1.16")

ALL_CIC = [
    # 1 government bond, fixed coupon, accrued interest
    position(
        "DE11",
        isin("DE000BU2Z02"),
        "1",
        "BUNDESANLEIHE 2.60% 15/08/2034",
        "EUR",
        "5115500",
        BUND,
        f19="5000000",
        f125="49000",
        f32="Fixed",
        f33="0.026",
        f38="1",
        f39="2034-08-15",
        f40="Bullet",
        f41="1",
        f63="2024-06-14",
        f57="Y",
        f90="7.4",
        f92="7.2",
        f94="0.61",
        f129="0.0262",
        f130="0",
    ),
    # 2 corporate floater, issuer without code (48 = 9), embedded call
    position(
        "FR21",
        isin("FR00140DEMO"),
        "1",
        "DEMO INDUSTRIES FRN 20/06/2029",
        "EUR",
        "3018000",
        DEMO_CORP,
        f19="3000000",
        f125="21000",
        f32="Floating",
        f33="0.0285",
        f34="EU0009652783",
        f35="1",
        f36="EURIBOR 3M",
        f37="0.009",
        f38="4",
        f39="2029-06-20",
        f40="Bullet",
        f41="1",
        f42="Cal",
        f43="2027-06-20",
        f44="I",
        f45="1",
        f63="2024-06-20",
        f90="0.2",
        f91="0.2",
        f92="3.3",
        f58="N",
        f142="1",
        f59="3",
        f112="BBB",
        f113="Demo Ratings",
    ),
    # 3 convertible bond with underlying equity
    position(
        "DE22",
        isin("DE000A3DEMO"),
        "1",
        "SIEMENS ENERGY 0.5% CV 2030",
        "EUR",
        "2350000",
        SIEMENS,
        f19="2000000",
        f125="4000",
        f32="Fixed",
        f33="0.005",
        f38="1",
        f39="2030-09-14",
        f40="Bullet",
        f41="1",
        f60="Cal",
        f61="78.74",
        f62="25.4",
        f64="EU",
        f127="0.92",
        f128="0.18",
        f67="DE31",
        f68="DE000ENER6Y0",
        f69="1",
        f70="SIEMENS ENERGY AG",
        f71="EUR",
        f72="48.5",
        f73="DE",
        f74="1",
        f80="SIEMENS ENERGY AG",
        f82="9",
        f83="SIEMENS ENERGY AG",
        f85="9",
        f86="DE",
        f93="0.45",
        f90="4.4",
        f92="4.2",
    ),
    # 3 equities: ISIN, CUSIP, SEDOL, WKN, Bloomberg ticker; USD and GBP
    position(
        "US31",
        "037833100",
        "2",
        "APPLE INC",
        "USD",
        "1000000",
        APPLE,
        f18="4000",
        f93="1",
    ),
    position(
        "NL31",
        "B929F46",
        "3",
        "ASML HOLDING NV",
        "EUR",
        "1260000",
        ASML,
        f18="2000",
        f93="1",
        f99="-491400",
    ),
    position(
        "DE31",
        "716460",
        "4",
        "SAP SE",
        "EUR",
        "1154400",
        SAP,
        f18="5000",
        f93="1",
    ),
    position(
        "GB31",
        "SHEL LN Equity",
        "5",
        "SHELL PLC",
        "GBP",
        "520000",
        SHELL,
        f18="20000",
        f93="1",
    ),
    # 3 private equity, internal code
    position(
        "XT34",
        "PE-DGP-II",
        "99",
        "DEMO GROWTH PARTNERS II",
        "EUR",
        "800000",
        GROWTH,
        f18="800",
        f111="650000",
        f134="1",
        f135="1.1",
    ),
    # 4 equity ETF (look-through id) and money market fund (FIGI)
    position(
        "IE41",
        "IE00B4L5Y983",
        "1",
        "ISHARES CORE MSCI WORLD UCITS ETF",
        "EUR",
        "1500000",
        BLACKROCK,
        f18="14337.6028",
        f95="IE00B4L5Y983",
        f93="1",
    ),
    position(
        "LU43",
        "BBG00DEMOMM1",
        "8",
        "DEMO EURO LIQUIDITY FUND I",
        "EUR",
        "1200000",
        MMF,
        f18="11650.4854",
    ),
    # 5 structured note (Bloomberg id), 6 securitisation tranche
    position(
        "XL52",
        "BBG01DEMOSN2",
        "6",
        "DEMO BANK RATE-LINKED NOTE 2028",
        "EUR",
        "990000",
        BANK,
        f18="1000",
        f32="Variable",
        f33="0.03",
        f38="1",
        f39="2028-03-01",
        f40="Bullet",
        f41="1",
        f125="0",
        f58="N",
        f90="2.1",
        f103="-29700",
    ),
    position(
        "IE61",
        isin("XS28DEMO123"),
        "1",
        "DEMO AUTO LOANS 2024-1 A",
        "EUR",
        "702000",
        SPV,
        f19="700000",
        f125="2000",
        f32="Floating",
        f33="0.034",
        f34="EU0009652783",
        f35="1",
        f36="EURIBOR 1M",
        f37="0.007",
        f38="12",
        f39="2031-11-20",
        f143="2028-05-20",
        f40="Sinkable",
        f41="1",
        f56="a",
        f58b="Senior",
        f146="1",
        f90="0.1",
        f144="2.3",
        f145="2.2",
    ),
    # 7 cash (EUR, USD), transferable deposit, term deposit
    position("XT71", "CASH-EUR", "99", "CASH ACCOUNT EUR", "EUR", "1850000", CUSTODIAN_ISSUER),
    position("XT71", "CASH-USD", "99", "CASH ACCOUNT USD", "USD", "250000", CUSTODIAN_ISSUER),
    position(
        "XT72",
        "DEP-SIGHT-01",
        "99",
        "SIGHT DEPOSIT DEMO BANK",
        "EUR",
        "400000",
        BANK,
        f125="0",
        f32="Fixed",
        f33="0.015",
        f38="0",
    ),
    position(
        "XT73",
        "DEP-TERM-01",
        "99",
        "TERM DEPOSIT 3M DEMO BANK",
        "EUR",
        "600000",
        BANK,
        f125="0",
        f32="Fixed",
        f33="0.021",
        f38="0",
        f39="2026-03-31",
        f63="2025-12-31",
    ),
    # 8 loan, 9 property, 0 other investment (RIC)
    position(
        "XT81",
        "LOAN-0001",
        "99",
        "DEMO MITTELSTAND TERM LOAN",
        "EUR",
        "500000",
        BORROWER,
        f19="500000",
        f125="0",
        f32="Fixed",
        f33="0.055",
        f38="4",
        f39="2030-12-31",
        f40="Sinkable",
        f41="1",
        f138="1",
        f139="550000",
        f132="2",
        f147="2",
    ),
    position(
        "XT91",
        "PROP-LUX-01",
        "99",
        "OFFICE BUILDING LUXEMBOURG KIRCHBERG",
        "EUR",
        "900000",
        PROPCO,
        f18="1",
        f101="-225000",
    ),
    position(
        "XL09",
        "XAU=",
        "7",
        "PHYSICAL GOLD CERTIFICATE",
        "USD",
        "450000",
        BANK,
        f18="200",
    ),
    # A futures: equity index (index ISIN as underlying) and interest rate future
    position(
        "XLA1",
        isin("DE000C7DEMO"),
        "1",
        "EURO STOXX 50 FUTURE MAR 2026",
        "EUR",
        "0",
        EUREX,
        f18="20",
        f20="10",
        f39="2026-03-20",
        f65="N",
        f67="XL31",
        f68="EU0009658145",
        f69="1",
        f70="EURO STOXX 50",
        f71="EUR",
        f72="4900",
        f27="980000",
        f29="980000",
        f31="0.0392",
        f93="1",
        f100="-382200",
    ),
    position(
        "XLA2",
        isin("DE000C6AXQV"),
        "1",
        "EURO BUND FUTURE MAR 2026",
        "EUR",
        "0",
        EUREX,
        f18="-5",
        f20="1000",
        f39="2026-03-10",
        f65="Y",
        f67="DE11",
        f68="DE000BU2Z023",
        f69="1",
        f70="BUNDESANLEIHE 2.60% 15/08/2034",
        f71="EUR",
        f72="128.6",
        f75="0.026",
        f76="1",
        f77="2034-08-15",
        f78="Bullet",
        f79="1",
        f80="BUNDESREPUBLIK DEUTSCHLAND",
        f81=BUND[1],
        f82="1",
        f83="BUNDESREPUBLIK DEUTSCHLAND",
        f84=BUND[1],
        f85="1",
        f86="DE",
        f87="1",
        f88="Y",
        f89="0",
        f27="-643000",
        f93="1",
    ),
    # B call and C put options, F2 credit spread option
    position(
        "XLB1",
        isin("DE000C8DEMO"),
        "1",
        "EURO STOXX 50 CALL 5000 JUN 2026",
        "EUR",
        "85000",
        EUREX,
        f18="100",
        f20="10",
        f39="2026-06-19",
        f60="Cal",
        f61="5000",
        f64="EU",
        f67="XL31",
        f62="1",
        f68="EU0009658145",
        f69="1",
        f70="EURO STOXX 50",
        f71="EUR",
        f72="4900",
        f93="0.42",
        f94b="11.5",
        f27="2058000",
    ),
    position(
        "XTC1",
        "OTC-PUT-SAP-01",
        "99",
        "SAP SE PUT 200 SEP 2026 OTC",
        "EUR",
        "42000",
        BANK,
        f18="30",
        f20="100",
        f39="2026-09-18",
        f60="Put",
        f61="200",
        f64="AM",
        f67="DE31",
        f62="1",
        f68="DE0007164600",
        f69="1",
        f70="SAP SE",
        f71="EUR",
        f72="230.88",
        f93="-0.31",
        f27="-214718",
    ),
    position(
        "XTF2",
        "OTC-CSO-01",
        "99",
        "ITRAXX MAIN CREDIT SPREAD OPTION",
        "EUR",
        "15000",
        BANK,
        f18="1",
        f20="5000000",
        f39="2026-06-20",
        f60="Put",
        f61="0.0065",
        f62="1",
        f64="EU",
        f67="XL21",
        f68="ITRAXX-EUR-MAIN-S44",
        f69="99",
        f70="ITRAXX EUROPE MAIN S44",
        f71="EUR",
        f72="0.0058",
        f27="5000000",
    ),
    # D swaps (interest rate, total return), F1 credit default swap
    position(
        "XTD1",
        "IRS-EUR-10Y-01",
        "99",
        "IRS PAY FIX 2.4% / REC EURIBOR 6M 2035",
        "EUR",
        "-35000",
        BANK,
        f16="IRS01",
        f19="10000000",
        f32="Fixed",
        f33="0.024",
        f38="1",
        f39="2035-12-31",
        f27="10000000",
        f97="-52000",
        f98="61000",
    ),
    position(
        "XTD4",
        "TRS-EQ-01",
        "9",
        "TOTAL RETURN SWAP ON DEMO EQUITY BASKET",
        "EUR",
        "12000",
        BANK,
        f19="2000000",
        f32="Floating",
        f33="0.03",
        f38="4",
        f39="2026-12-31",
        f27="2000000",
        f99="-480000",
    ),
    position(
        "XTF1",
        "CDS-ITRAXX-01",
        "99",
        "CDS ITRAXX EUROPE MAIN S44 5Y",
        "EUR",
        "-8000",
        BANK,
        f19="3000000",
        f32="Fixed",
        f33="0.01",
        f38="4",
        f39="2030-12-20",
        f27="3000000",
        f92="4.6",
        f102="-21000",
        f104="-24000",
        f105="19000",
    ),
    # E2 FX forward, E1 forward rate agreement
    position(
        "XTE2",
        "FXF-EURUSD-01",
        "99",
        "FX FORWARD SELL USD 1.2M / BUY EUR MAR 2026",
        "USD",
        "9000",
        BANK,
        f16="FXF01",
        f19="1200000",
        f32="Fixed",
        f33="0",
        f38="0",
        f39="2026-03-18",
        f27="1200000",
        f105a="-110000",
        f105b="98000",
    ),
    position(
        "XTE1",
        "FRA-3X6-01",
        "99",
        "FRA 3X6 EURIBOR 2.1%",
        "EUR",
        "2500",
        BANK,
        f18="1",
        f19="5000000",
        f20="1",
        f32="Fixed",
        f33="0.021",
        f38="0",
        f39="2026-06-30",
        f27="5000000",
    ),
]

RATES = {"EUR": Decimal(1), "USD": USD_EUR, "GBP": GBP_EUR}


def build_portfolio(portfolio: dict, positions: list[dict], shares: str) -> list[dict]:
    """Rows of one TPT portfolio, amounts in the portfolio currency (field 4) reconciled."""
    pc = portfolio["4"]
    rows = []
    for pos in positions:
        values = {**portfolio, **pos}
        rate = RATES[values["21"]] / RATES[pc]
        values["24"] = amount(Decimal(values["22"]) * rate)
        exposure = Decimal(values["27"]) * rate if values.get("27") else None
        if exposure is not None:
            values["28"] = amount(exposure)
        complete_position(values, exposure, rate)
        rows.append(values)
    nav = sum(Decimal(r["24"]) for r in rows)
    for r in rows:
        r["5"] = amount(nav)
        r["26"] = format_decimal((Decimal(r["24"]) / nav).quantize(Decimal("1E-6"), ROUND_HALF_UP))
        if r.get("28"):
            r["30"] = format_decimal((Decimal(r["28"]) / nav).quantize(Decimal("1E-6"), ROUND_HALF_UP))
        r["8b"] = shares
        r["8"] = format_decimal((nav / Decimal(shares)).quantize(Decimal("0.0001"), ROUND_HALF_UP))
    complete_portfolio(rows)
    return rows


def portfolio_fields(sc_isin: str, name: str, ccy: str, **fields) -> dict:
    values = {
        "1": sc_isin,
        "2": "1",
        "3": name,
        "4": ccy,
        "6": VALUATION,
        "7": VALUATION,
        "10": "3.85",
        "11": "Y",
        "115": MANCO[1],
        "116": "1",
        "117": MANCO[0],
        "118": "K6630",
        "119": MANCO[1],
        "120": "1",
        "121": MANCO[2],
        "122": "LU",
        "123": "LU41",
        "123a": CUSTODIAN[2],
        "124": "3.92",
        "133": CUSTODIAN[0],
        "140": CUSTODIAN[1],
        "141": "1",
        "1000": VERSION_LABELS["V7"],
    }
    values.update({k[1:]: str(v) for k, v in fields.items()})
    return values


def all_cic_rows() -> list[dict]:
    pf = portfolio_fields(isin("LU2900DEMO1"), "Demo Global Multi Asset Fund A EUR", "EUR")
    return build_portfolio(pf, ALL_CIC, "250000")


# -- several funds and share classes ---------------------------------------------------------

_FUND_A = [ALL_CIC[0], ALL_CIC[1], ALL_CIC[3], ALL_CIC[5], ALL_CIC[8], ALL_CIC[12], ALL_CIC[13], ALL_CIC[19]]
_FUND_B = [
    position(
        "DE11",
        isin("DE0001102DE"),
        "1",
        "BUNDESANLEIHE 0% 15/02/2031",
        "EUR",
        "4400000",
        BUND,
        f19="5000000",
        f125="0",
        f32="Fixed",
        f33="0",
        f38="0",
        f39="2031-02-15",
        f40="Bullet",
        f41="1",
        f57="Y",
        f90="5.0",
    ),
    position("DE31", "DE0007164600", "1", "SAP SE", "EUR", "2308800", SAP, f18="10000", f93="1"),
    position("XT71", "CASH-EUR-B", "99", "CASH ACCOUNT EUR", "EUR", "291200", CUSTODIAN_ISSUER),
]


def multi_fund_rows() -> list[dict]:
    """Fund A with three share classes (EUR distributing, EUR institutional, USD hedged), fund B."""
    fund_a = "Demo Balanced Fund"
    rows = []
    for sc_isin, suffix, ccy, shares in (
        (isin("LU2900BAL01"), "A EUR", "EUR", "120000"),
        (isin("LU2900BAL02"), "I EUR", "EUR", "8000"),
        (isin("LU2900BAL03"), "A USD H", "USD", "45000"),
    ):
        pf = portfolio_fields(sc_isin, f"{fund_a} {suffix}", ccy, f123="LU44")
        rows += build_portfolio(pf, _FUND_A, shares)
    pf = portfolio_fields(
        isin("DE000DEMOB0"),
        "Demo Deutschland Rent",
        "EUR",
        f115="",
        f116="9",
        f117="DEMO KVG MBH",
        f119="",
        f120="9",
        f121="DEMO KVG MBH",
        f122="DE",
        f123="DE42",
        f123a="DE",
        f10="5.1",
        f124="5.0",
    )
    rows += build_portfolio(pf, _FUND_B, "70000")
    return rows


# -- a file with gaps and errors -------------------------------------------------------------


def error_rows() -> list[dict]:
    """Copies of clean rows with typical delivery errors (each reported by the converter)."""
    rows = [dict(r) for r in all_cic_rows()[:8]]
    for r in rows:
        r.pop("5")  # NAV missing (mandatory)
    rows[1]["12"] = "FR2"  # truncated CIC
    rows[2]["21"] = "EURO"  # not an ISO currency
    rows[3]["39"] = "31.02.2030"  # impossible date
    rows[4]["15"] = "77"  # code type outside the list
    rows[5].pop("14")  # instrument code missing
    rows[6]["26"] = "zwölf"  # not a number
    rows[7]["32"] = "Fix"  # outside the closed list
    return rows


# -- openfunds share class data --------------------------------------------------------------

OF_FUND_STATIC = {
    "OFST010020": "Demo Funds SICAV - Global Multi Asset",
    "OFST010410": "EUR",
    "OFST010030": lei("529900DEMOGLOBALMA"),
    "OFST002900": "A1B2C3.99999.SL.442",
    "OFST010075": "12345",
    "OFST005030": "O00001234",
    "OFST010010": "LU",
    "OFST160040": "UCITS",
    "OFST010240": "2015-03-02",
    "OFST010440": "12-31",
    "OFST010420": "open-ended fund",
    "OFST001040": "no",
    "OFST010211": "yes, partial hedge",
    "OFST001000": "Demo Asset Management",
    "OFST001020": MANCO[0],
    "OFST001030": MANCO[1],
    "OFST001035": "LU",
    "OFST001055": "15, rue de la Démo",
    "OFST001060": "Luxembourg",
    "OFST001070": "L-1855",
    "OFST001075": "+352 260000 1",
    "OFST001021": "funds@demo-am.example",
    "OFST001065": "https://demo-am.example",
    "OFST001400": CUSTODIAN[0],
    "OFST001410": CUSTODIAN[1],
    "OFST001420": "DEMOLULLXXX",
    "OFST001415": "LU",
    "OFST001300": "Demo Fund Administration S.A.",
    "OFST001600": "Demo Audit S.à r.l.",
    "OFST001100": "Demo Bank AG",
    "OFST001105": lei("529900DEMOPROMOTER"),
    "OFST001510": "Demo Quant Advisors Ltd",
    "OFST001520": "Demo Legal Partners",
    "OFST001540": "Demo Distribution GmbH",
    "OFST700400": "Demo Domiciliation S.A.",
    "OFST001450": "Demo Portfolio Management GmbH",
    "OFST001455": "DE",
    "OFST001500": "Demo Investment Advisory AG",
    "OFST001440": CUSTODIAN[0],
    "OFST001445": CUSTODIAN[1],
    "OFST001900": "Demo Collateral Services",
    "OFST011010": "Demo Securities Lending Ltd",
    "OFST011110": BANK[0],
    "OFST350100": "Multi-Asset",
    "OFST350110": "Multi-Asset Flexible",
    "OFST700500": "Diversifiés",
    "OFST701030": "Mixed Investment 40-85% Shares",
    "OFST809511": "Participating FFI",
    "OFST710095": "MX",
    "OFST710100": "721",
    "OFST010080": "B12345",
    "OFST005035": "B00123",
    "OFST010090": "K55501",
    "OFST6102CH": "Demo Representative Switzerland AG",
    "OFST6107CH": "Demo Paying Agent Switzerland AG",
    "OFST350000": "non-complex instrument",
    "OFST730010": "MIX-FLEX",
    "OFST350050": "Balanced Fund (BLF)",
    "OFST700601": "excluded investment products (EIP)",
    "OFST710110": "non-complex",
    "OFST452200": "0.0142",
    "OFST452220": "2025-02-15",
    "OFST010580": "no",
    "OFST010500": "no",
    "OFST010720": "no",
    "OFPM000010": "Erika Mustermann",
    "OFPM000120": "2019-04-01",
    "OFPM000111": "lead",
    "OFPM000020": "1978",
    "OFDY000061": VALUATION,
    "OFDY000060": "182500000",
}

_SC_COMMON = {
    "OFST023100": "open",
    "OFST010630": "no",
    "OFST451155": "no",
    "OFST451042": "0.0005",
    "OFST451065": "0.001",
    "OFST002700": "Demo Transfer Agency S.A.",
    "OFST002705": "DEMOLULLTAX",
    "OFST002710": "LU",
    "OFST6030LU": "yes",
    "OFST6010LU": "2015-03-02",
    "OFST6031LU": "yes",
    "OFST6020LU": "2015-03-02",
    "OFST6030AT": "yes",
    "OFST6010AT": "2016-01-15",
    "OFST6030CH": "res",  # restricted: registered, the value stays as custom attribute
    "OFST6030GB": "no",
    "OFST6011GB": "2021-01-01",  # no longer registered: De-registered
    "OFST6031DE": "no",
    "OFST6021DE": "2024-06-30",
    "OFDY000036": VALUATION,
    "OFDY000071": VALUATION,
}

OF_SHARECLASSES = [
    {
        **OF_FUND_STATIC,
        **_SC_COMMON,
        "OFST020000": isin("LU2900GMA01"),
        "OFST020005": "L2900G101",
        "OFST020010": "123456789",
        "OFST020015": "A2DEMO",
        "OFST020020": "DEMGMAA LX",
        "OFST020025": "BBG00DEMOGM1",
        "OFST020040": "BD4MQZ9",
        "OFST350015": "CEOGMU",
        "OFST020105": "54321",
        "OFST060010": "LU2900GMA01.LU",
        "OFST020060": "Demo Funds SICAV - Global Multi Asset A EUR dis",
        "OFST020070": "Global MA A EUR",
        "OFST020540": "EUR",
        "OFST020050": "A",
        "OFST020400": "distributing",
        "OFST020560": "2015-03-02",
        "OFST020261": "no",
        "OFST808500": "no",
        "OFST400240": "EUR",
        "OFST400230": "1000",
        "OFST400260": "100",
        "OFST452010": "0.015",
        "OFST452005": "0.005",
        "OFST454165": "0.005",
        "OFDY000035": "118.42",
        "OFDY000020": "118.42",
        "OFDY000025": "121.97",
        "OFDY000070": "71038000",
        "OFDY000075": "599882.79",
        "OFDY005030": "yes",
        "OFDY005005": "2025-11-20",
        "OFDY005007": "2025-12-02",
        "OFDY005010": "2025-12-01",
        "OFDY005015": "2025-12-05",
        "OFDY005000": "EUR",
        "OFDY005020": "1.85",
        "OFDY005022": "1.36",
    },
    {
        **OF_FUND_STATIC,
        **_SC_COMMON,
        "OFST020000": isin("LU2900GMA02"),
        "OFST020060": "Demo Funds SICAV - Global Multi Asset I EUR acc",
        "OFST020540": "EUR",
        "OFST020050": "I",
        "OFST020400": "accumulating",
        "OFST020560": "2016-09-01",
        "OFST020261": "no",
        "OFST400220": "100",
        "OFST400250": "1",
        "OFST451155": "yes",
        "OFST451160": "high water mark, no reset",
        "OFST452010": "0.007",
        "OFST401003": "partial swing NAV",
        "OFST020035": "QS0012345678",
        "OFST020037": "12345_67_89",
        "OFST020042": "DEM0001AU",
        "OFST020045": "DGMIX",
        "OFST020047": "KR5DEMO00001",
        "OFIN000010": "INV-000417",
        "OFIN000130": "50000",
        "OFIN000410": VALUATION,
        "OFDY000035": "1342.10",
        "OFDY000040": "1344.95",
        "OFDY000070": "98500000",
        "OFDY000075": "73392.44",
    },
    {
        **OF_FUND_STATIC,
        **_SC_COMMON,
        "OFST020000": isin("LU2900GMA03"),
        "OFST020060": "Demo Funds SICAV - Global Multi Asset A USD hedged",
        "OFST020540": "USD",
        "OFST020050": "A USD H",
        "OFST020400": "accumulating",
        "OFST020560": "2018-05-14",
        "OFST020261": "yes, full NAV hedge",
        "OFST452015": "0.018",
        "OFDY000010": "USD",
        "OFDY000035": "141.03",
        "OFDY000070": "14158000",
        "OFDY000076": "2025-12-30",  # number of shares from another date: custom attribute
        "OFST020566": "2026-06-30",  # liquidation announced
        "OFDY000075": "100390.0",
        "OFST6030CH": "",
        "OFST6030US": "no",
    },
]

# A second fund: an index-tracking ETF with its listing
_ETF = {
    "OFST010020": "Demo ETF ICAV - Euro Stoxx 50 UCITS ETF",
    "OFST010410": "EUR",
    "OFST010030": lei("635400DEMOETFICAV0"),
    "OFST005025": "C123456",
    "OFST010070": "C654321",
    "OFST010010": "IE",
    "OFST160040": "UCITS",
    "OFST010240": "2020-06-01",
    "OFST010440": "06-30",
    "OFST010420": "open-ended fund",
    "OFST001020": "Demo ETF Management Ltd",
    "OFST001035": "IE",
    "OFST001400": "Demo Depositary Ireland DAC",
    "OFST001430": "Demo Trustee Services DAC",
    "OFST002000": "Demo Market Making B.V.",
    "OFST001050": "Demo Guarantee Bank AG",
    "OFST010580": "yes",
    "OFST010720": "yes",
    "OFST023800": "EURO STOXX 50 Net Return",
    "OFST023805": "EUR",
    "OFST350100": "Equity",
    "OFST020000": isin("IE000DEMO50"),
    "OFST020060": "Demo Euro Stoxx 50 UCITS ETF EUR acc",
    "OFST020050": "EUR acc",
    "OFST020540": "EUR",
    "OFST020400": "accumulating",
    "OFST020560": "2020-06-01",
    "OFST808500": "yes",
    "OFST6030IE": "yes",
    "OFST6030DE": "yes",
    "OFST6031DE": "yes",
    "OFST6020DE": "2020-07-01",
    "OFDY000036": VALUATION,
    "OFDY000035": "52.18",
    "OFDY000076": VALUATION,  # without a volume date the number-of-shares date is the NAV date
    "OFDY000070": "640200000",
    "OFDY000075": "12269000",
    "OFDY000061": VALUATION,
    "OFDY000060": "640200000",
    "OFDY000066": VALUATION,
    "OFDY000065": "12269000",
}
OF_ETF = {
    **_ETF,
    "OFST062030": "XETR",
    "OFST062010": "EUR",
    "OFST060050": "DEMO50IV GY",
    "OFST060060": "DEMO50iv.DE",
}

# Static data for the share classes of multi_fund_rows (fund A: three classes, fund B: one)
_BALANCED = {
    "OFST010020": "Demo Balanced Fund",
    "OFST010410": "EUR",
    "OFST010010": "LU",
    "OFST160040": "UCITS",
    "OFST010420": "open-ended fund",
    "OFST001020": MANCO[0],
    "OFST001400": CUSTODIAN[0],
    "OFST023100": "open",
    "OFST6030LU": "yes",
    "OFST6030DE": "yes",
}
OF_MULTI_STATIC = [
    {**_BALANCED, "OFST020050": "A", "OFST020400": "distributing", "OFST452010": "0.012"},
    {**_BALANCED, "OFST020050": "I", "OFST020400": "accumulating", "OFST452010": "0.006"},
    {
        **_BALANCED,
        "OFST020050": "A USD H",
        "OFST020400": "accumulating",
        "OFST020261": "yes, full NAV hedge",
        "OFST452010": "0.012",
    },
    {
        "OFST010020": "Demo Deutschland Rent",
        "OFST010410": "EUR",
        "OFST010010": "DE",
        "OFST160040": "UCITS",
        "OFST001020": "DEMO KVG MBH",
        "OFST001032": "123456",
        "OFST010800": "2031-02-15",  # term fund
        "OFDY000066": VALUATION,  # number of fund shares without an AuM date
        "OFDY000065": "70000",
        "OFST020050": "R",
        "OFST020400": "distributing",
        "OFST6030DE": "yes",
        "OFST6030AT": "yes",
    },
]
