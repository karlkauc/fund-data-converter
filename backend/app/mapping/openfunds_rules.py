"""openfunds field ↔ FundsXML path rules (static and dynamic share class data).

One openfunds record is one share class at one date. Rules map an OF-ID to a path in the regular
FundsXML structures; every field without a rule (or whose value a rule cannot express) is kept by
the engine as ``CustomAttributes/Attribute[Name=OF_<OF-ID>]``, so only semantically genuine
counterparts are mapped here.

Rule contexts (the node a path is relative to):

=================  ==========================================================
``of_fund``        Funds/Fund (incl. FundStaticData and FundDynamicData)
``of_shareclass``  Funds/Fund/SingleFund/ShareClasses/ShareClass
=================  ==========================================================

Paths may contain ``{OF-ID}`` placeholders, replaced with the value of another field of the same
record (e.g. the currency in ``Amount[@ccy={OFST020540}]``); the rule is skipped if it is empty.
``DEFAULTS`` lists constant mandatory children the engine adds when their parent exists.

Deliberately not mapped (kept as custom attributes): subscription/redemption fees (FundsXML
``Fee`` values are a percentage of TNA paid/received by the fund), applied fees, TER and other
period figures (``Fee/DataByPeriods`` needs a begin/end period), transaction costs, fund texts
(language and date mandatory), ``OFST023200 Benchmark`` (FundsXML needs a benchmark currency),
``OFST020600 Is RDR Compliant`` (``UK_RDR_Flag`` means "retail only"), OFRE ratios/breakdowns,
OFDC cost figures, OFFV fair values and OFCA corporate actions (no core counterpart), and the
Austrian ``OeKBStammdatenblatt`` (too many mandatory fields without an openfunds source).
"""

from __future__ import annotations

from app.mapping import transforms as t
from app.mapping.rules import Condition, Rule, _r, field_is
from app.mapping.transforms import Transform, _mapping

OF_FUND = "of_fund"
OF_SHARECLASS = "of_shareclass"

_F, _S = OF_FUND, OF_SHARECLASS


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def _yes_no_to(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
    low = v.strip().lower()
    if low in ("yes", "true", "y", "1"):
        return "true", low == "yes"
    if low in ("no", "false", "n", "0"):
        return "false", low == "no"
    return None, False


def _yes_no_from(v: str, _ctx: dict[str, str]) -> str | None:
    return {"true": "yes", "1": "yes", "false": "no", "0": "no"}.get(v.strip().lower())


YES_NO = Transform("yes_no", _yes_no_to, _yes_no_from, "openfunds yes/no ↔ xs:boolean")

DISTRIBUTION_POLICY = _mapping(
    "distribution_policy",
    {"distributing": "D", "accumulating": "R", "accumulating & distributing": "P"},
    "distribution policy ↔ EarningUse (D/R/P)",
)
HEDGE_SHARECLASS_TABLE = {
    "no": "No hedge",
    "yes, full NAV hedge": "Full NAV hedge",
    "yes, partial NAV hedge": "Partial hedge",
}
HEDGE_SHARECLASS = _mapping(
    "hedge_shareclass", HEDGE_SHARECLASS_TABLE, "share class currency hedge ↔ HedgingStrategy"
)
HEDGE_PORTFOLIO = _mapping(
    "hedge_portfolio",
    {
        "no": "No hedge",
        "yes, full portfolio hedge": "Full Portfolio hedge",
        "yes, partial hedge": "Partial hedge",
    },
    "portfolio currency hedge ↔ HedgingStrategy",
)


def _hedged_flag_to(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
    low = v.strip().lower()
    if low == "no":
        return "false", False
    if low.startswith("yes"):
        return "true", False
    return None, False


CURRENCY_HEDGED_FLAG = Transform(
    "currency_hedged_flag",
    _hedged_flag_to,
    lambda _v, _c: None,
    "no → false, yes… → true (one-way; the value is kept as custom attribute)",
)
OPEN_CLOSED = _mapping(
    "open_closed", {"open-ended fund": "OPEN", "closed-ended fund": "CLOSED"}, "fund structure ↔ OPEN/CLOSED"
)
LEGAL_STRUCTURE = _mapping("eu_directive", {"UCITS": "UCITS", "AIF": "AIF"}, "EU directive ↔ legal structure")
DIVIDEND_STATUS = _mapping(
    "dividend_status", {"yes": "OFFICIAL", "no": "ESTIMATED"}, "final ↔ OFFICIAL, estimated ↔ ESTIMATED"
)
HWM_RESET = _mapping(
    "hwm_reset",
    {"high water mark, reset": "true", "high water mark, no reset": "false"},
    "high water mark type ↔ PeriodicalResetFlag",
)


def _lossy_table(name: str, exact: dict[str, str], lossy: dict[str, str], note: str) -> Transform:
    """Like ``_mapping``; values in ``lossy`` map too, but the original is kept as custom attribute."""
    back = {v: k for k, v in exact.items()}

    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        low = v.strip().lower()
        for table, lossless in ((exact, True), (lossy, False)):
            for k, val in table.items():
                if k.lower() == low:
                    return val, lossless
        return None, False

    return Transform(name, to_xml, lambda v, _c: back.get(v.strip()), note)


INVESTMENT_STATUS_OPEN = _lossy_table(
    "investment_status_open",
    {"open": "true"},
    {
        "closed for redemption": "true",
        "soft closed": "false",
        "hard closed": "false",
        "closed for subscription and redemption": "false",
    },
    "investment status → open to new investors (only 'open' is read back)",
)
DEREGISTERED = _mapping(
    "deregistered", {"no": "De-registered"}, "'no' with a deregistration/end date ↔ De-registered"
)
MANAGEMENT_TYPE = _mapping("management_type", {"yes": "PASSIVE", "no": "ACTIVE"}, "passive fund ↔ PASSIVE")
REGISTRATION_STATUS = _lossy_table(
    "registration_status",
    {"yes": "Registered"},
    {"res": "Registered"},
    "yes/res (restricted) → Registered; 'no' (never or no longer registered) is not mapped",
)


def _part(name: str, index: int, sep: str, note: str) -> Transform:
    """One part of a composite value; the whole value is kept as custom attribute."""

    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        parts = [p for p in v.strip().split(sep) if p] if sep != " " else v.split()
        return (parts[index] if len(parts) > index else None), False

    return Transform(name, to_xml, lambda _v, _c: None, note)


def _month_day(index: int, name: str) -> Transform:
    # openfunds "MM-DD" (also "--MM-DD" or a full "YYYY-MM-DD" date): index -2 = month, -1 = day.
    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        parts = [p for p in v.strip().split("-") if p]
        if len(parts) < 2 or not all(p.isdigit() for p in parts[-2:]):
            return None, False
        return str(int(parts[index])), False

    return Transform(name, to_xml, lambda _v, _c: None, "fiscal year end MM-DD split into month and day")


FY_MONTH = _month_day(-2, "fiscal_year_end_month")
FY_DAY = _month_day(-1, "fiscal_year_end_day")
BBG_TICKER = _part("bloomberg_ticker", 0, " ", "ticker part of 'TICKER XX'")
BBG_EXCHANGE = _part("bloomberg_exchange", 1, " ", "exchange part of 'TICKER XX'")


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def _empty(key: str) -> Condition:
    return lambda row: not row.get(key, "").strip()


def _same_date(key: str, ref: str) -> Condition:
    """``key`` is empty or equal to ``ref`` (both dates of the same record)."""
    return lambda row: not row.get(key, "").strip() or row.get(key, "").strip() == row.get(ref, "").strip()


def _never(_row: dict[str, str]) -> bool:
    return False


def _always(_row: dict[str, str]) -> bool:
    return True


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

_FSD = "FundStaticData"
_SFSD = "SingleFund/SingleFundStaticData"
_IC = f"{_FSD}/InvestmentCompany"
_CUST = f"{_FSD}/Custodian"
_SC_ID = "Identifiers"


def _company(role: str, listed: bool = True) -> str:
    pred = "ListedRole" if listed else "UnlistedRole"
    return f"{_FSD}/Companies/Company[{pred}={role}]/Details"


def _other_id(base: str, listed_type: str) -> str:
    return f"{base}/OtherID[@ListedType={listed_type}]"


def _free_id(base: str, free_type: str) -> str:
    return f"{base}/OtherID[@FreeType={free_type}]"


_FUND_RULES: list[Rule] = [
    # -- fund identity
    _r("OFST010020", _F, "Names/OfficialName"),
    _r("OFST010410", _F, "Currency"),
    _r("OFST010030", _F, "Identifiers/LEI"),
    _r("OFST002900", _F, _other_id("Identifiers", "GIIN CODE")),
    # CSSF/CBI/FSMA: the openfunds fund is the "sub-fund" in their terms, the umbrella the "fund".
    _r("OFST010075", _F, _other_id("Identifiers", "CSSF SUBFUND CODE")),
    _r("OFST005030", _F, _other_id("Identifiers", "CSSF FUND CODE")),
    _r("OFST010070", _F, _other_id("Identifiers", "CBI SUB FUND CODE")),
    _r("OFST005025", _F, _other_id("Identifiers", "CBI FUND CODE")),
    _r("OFST010080", _F, _other_id("Identifiers", "FSMA SUBFUND CODE")),
    _r("OFST005035", _F, _other_id("Identifiers", "FSMA FUND CODE")),
    _r("OFST710100", _F, _other_id("Identifiers", "CNMV CODE")),
    _r("OFST010090", _F, _free_id("Identifiers", "KOFIA FUND CODE")),
    # -- static data
    _r("OFST010010", _F, f"{_FSD}/DomicileCountry"),
    _r("OFST160040", _F, f"{_FSD}/ListedLegalStructure", LEGAL_STRUCTURE),
    _r("OFST010240", _F, f"{_FSD}/InceptionDate"),
    _r("OFST010440", _F, f"{_FSD}/EndOfFiscalYear/Day", FY_DAY),
    _r("OFST010440", _F, f"{_FSD}/EndOfFiscalYear/Month", FY_MONTH),
    _r("OFST010420", _F, f"{_FSD}/OpenClosedEnded", OPEN_CLOSED),
    _r("OFST010800", _F, f"{_FSD}/MaturityDate"),
    _r("OFST001040", _F, f"{_FSD}/SelfManagedSICAVFlag", YES_NO),
    _r("OFST010211", _F, f"{_FSD}/FundHedgingStrategy/HedgingStrategy", HEDGE_PORTFOLIO),
    # -- management company
    _r("OFST001020", _F, f"{_IC}/Name"),
    _r("OFST001030", _F, f"{_IC}/Identifiers/LEI"),
    _r("OFST001032", _F, _other_id(f"{_IC}/Identifiers", "BAFIN ID")),
    _r("OFST001035", _F, f"{_IC}/Address/Country"),
    _r("OFST001055", _F, f"{_IC}/Address/StreetName"),
    _r("OFST001060", _F, f"{_IC}/Address/CityName"),
    _r("OFST001070", _F, f"{_IC}/Address/CityCode"),
    _r("OFST001075", _F, f"{_IC}/Address/Phone"),
    _r("OFST001021", _F, f"{_IC}/Address/Email"),
    _r("OFST001065", _F, f"{_IC}/Address/Homepage"),
    # -- other service providers
    _r("OFST001400", _F, f"{_CUST}/Name"),
    _r("OFST001410", _F, f"{_CUST}/Identifiers/LEI"),
    _r("OFST001420", _F, f"{_CUST}/Identifiers/SwiftBIC"),
    _r("OFST001415", _F, f"{_CUST}/Address/Country"),
    _r("OFST001300", _F, f"{_FSD}/Administrator/Name"),
    _r("OFST001600", _F, f"{_FSD}/Auditor/Name"),
    _r("OFST001100", _F, f"{_company('Fund Promoter')}/Name"),
    _r("OFST001105", _F, f"{_company('Fund Promoter')}/Identifiers/LEI"),
    _r("OFST001510", _F, f"{_company('Sub Investment Advisor')}/Name"),
    _r("OFST001520", _F, f"{_company('Legal Advisor')}/Name"),
    _r("OFST001540", _F, f"{_company('Distributing Agent')}/Name"),
    _r("OFST700400", _F, f"{_company('Domiciliary Agent')}/Name"),
    _r("OFST6102CH", _F, f"{_company('Swiss Representative')}/Name"),
    _r("OFST6107CH", _F, f"{_company('Swiss Paying Agent')}/Name"),
    _r("OFST001450", _F, f"{_SFSD}/Managers/Manager/Name"),
    _r("OFST001455", _F, f"{_SFSD}/Managers/Manager/Address/Country"),
    _r("OFST001500", _F, f"{_SFSD}/Advisor/Name"),
    _r("OFST001430", _F, f"{_company('Trustee', False)}/Name"),
    _r("OFST001440", _F, f"{_company('Depository', False)}/Name"),
    _r("OFST001445", _F, f"{_company('Depository', False)}/Identifiers/LEI"),
    _r("OFST001050", _F, f"{_company('Fund Guarantor', False)}/Name"),
    _r("OFST001900", _F, f"{_company('Collateral Manager', False)}/Name"),
    _r("OFST002000", _F, f"{_company('Market Maker', False)}/Name"),
    _r("OFST011010", _F, f"{_company('Securities Lending Counterparty', False)}/Name"),
    _r("OFST011110", _F, f"{_company('Swap Counterparty', False)}/Name"),
    # -- classifications
    _r("OFST350100", _F, f"{_FSD}/Classifications/Classification[ListedGroup=EFAMA]/Value[@level=1]"),
    _r("OFST350110", _F, f"{_FSD}/Classifications/Classification[ListedGroup=EFAMA]/Value[@level=2]"),
    _r("OFST350000", _F, f"{_FSD}/Classifications/Classification[ListedGroup=MIFID]/Value"),
    _r("OFST700500", _F, f"{_FSD}/Classifications/Classification[ListedGroup=AMF]/Value"),
    _r("OFST730010", _F, f"{_FSD}/Classifications/Classification[ListedGroup=BVI]/Value"),
    _r("OFST701030", _F, f"{_FSD}/Classifications/Classification[ListedGroup=IMA]/Value"),
    _r("OFST809511", _F, f"{_FSD}/Classifications/Classification[ListedGroup=FATCA]/Value"),
    _r("OFST710095", _F, f"{_FSD}/Classifications/Classification[UnlistedGroup=CNMV]/Value"),
    _r(
        "OFST350050",
        _F,
        f"{_FSD}/Classifications/Classification[UnlistedGroup=Clearstream Fund Centre]/Value",
    ),
    _r("OFST700601", _F, f"{_FSD}/Classifications/Classification[UnlistedGroup=MAS]/Value"),
    _r("OFST710110", _F, f"{_FSD}/Classifications/Classification[UnlistedGroup=HK SFC]/Value"),
    # -- ongoing charges (UCITS KIID figure, decimal fraction) with its calculation date
    _r("OFST452200", _F, f"{_FSD}/OngoingCosts/OngoingCost[CostType=Ongoing Charges]/Percentage", t.PCT100),
    _r("OFST452220", _F, f"{_FSD}/OngoingCosts/OngoingCost[CostType=Ongoing Charges]/PublicationDate"),
    # -- single fund static data
    _r("OFST010580", _F, f"{_SFSD}/ExchangeTradedFlag", YES_NO),
    _r("OFST010500", _F, f"{_SFSD}/FundOfFundFlag", YES_NO),
    _r("OFST010720", _F, f"{_SFSD}/ManagementType", MANAGEMENT_TYPE),
    _r("OFST710102", _F, f"{_SFSD}/IsFeederFor/ISIN"),
    # -- tracked index (index funds): only the index fields give the mandatory currency; the name
    # doubles as BenchmarkID (the schema keys benchmarks by it)
    _r("OFST023800", _F, f"{_FSD}/Benchmarks/Benchmark[BenchmarkID={{OFST023800}}]/Name"),
    _r("OFST023805", _F, f"{_FSD}/Benchmarks/Benchmark[BenchmarkID={{OFST023800}}]/Currency"),
    # -- portfolio managers (one OFPM record per manager)
    _r("OFPM000010", _F, f"{_FSD}/PortfolioManagers/PortfolioManager[Name={{OFPM000010}}]/Name"),
    _r("OFPM000120", _F, f"{_FSD}/PortfolioManagers/PortfolioManager[Name={{OFPM000010}}]/StartDate"),
    _r("OFPM000111", _F, f"{_FSD}/PortfolioManagers/PortfolioManager[Name={{OFPM000010}}]/Role"),
    _r("OFPM000020", _F, f"{_FSD}/PortfolioManagers/PortfolioManager[Name={{OFPM000010}}]/YearOfBirth"),
]

_FUND_TAV = "FundDynamicData/TotalAssetValues/TotalAssetValue"
_FUND_DYNAMIC_RULES: list[Rule] = [
    _r("OFDY000061", _F, f"{_FUND_TAV}/NavDate"),
    _r(
        "OFDY000066",
        _F,
        f"{_FUND_TAV}/NavDate",
        when=_empty("OFDY000061"),
        when_text="OFDY000061 empty",
        reverse_when=_never,
    ),
    _r("OFDY000060", _F, f"{_FUND_TAV}/TotalNetAssetValue/Amount[@ccy={{OFST010410}}]"),
    _r(
        "OFDY000065",
        _F,
        f"{_FUND_TAV}/SharesOutstanding",
        when=lambda row: _empty("OFDY000061")(row) or _same_date("OFDY000066", "OFDY000061")(row),
        when_text="OFDY000066 empty or equal to OFDY000061",
    ),
]

_TAV = "TotalAssetValues/TotalAssetValue"
_PRICE = "Prices/Price"
_DIST = "Distributions/Distribution"
_SWING = field_is("OFST401003", "full swing NAV", "partial swing NAV")

_SHARECLASS_RULES: list[Rule] = [
    # -- identity
    _r("OFST020000", _S, f"{_SC_ID}/ISIN"),
    _r("OFST020005", _S, f"{_SC_ID}/CUSIP"),
    _r("OFST020010", _S, f"{_SC_ID}/SwissValorenCode"),
    _r("OFST020015", _S, f"{_SC_ID}/GermanWKN"),
    _r("OFST020020", _S, f"{_SC_ID}/Bloomberg/Ticker", BBG_TICKER),
    _r("OFST020020", _S, f"{_SC_ID}/Bloomberg/Exchange", BBG_EXCHANGE),
    _r("OFST020025", _S, f"{_SC_ID}/FIGI"),
    _r("OFST020040", _S, f"{_SC_ID}/SEDOL"),
    _r("OFST350015", _S, f"{_SC_ID}/CFI"),
    _r("OFST020035", _S, _other_id(_SC_ID, "AMF CODE")),
    _r("OFST020037", _S, _other_id(_SC_ID, "SWISS FUND DATA SHARECLASS CODE")),
    _r("OFST020105", _S, _other_id(_SC_ID, "CSSF SHARECLASS CODE")),
    _r("OFST060010", _S, _other_id(_SC_ID, "REUTERS LISTING CODE")),
    _r("OFST060050", _S, _other_id(_SC_ID, "INAV BLOOMBERG LISTING CODE")),
    _r("OFST060060", _S, _other_id(_SC_ID, "INAV REUTERS LISTING CODE")),
    _r("OFST020042", _S, _free_id(_SC_ID, "APIR CODE")),
    _r("OFST020045", _S, _free_id(_SC_ID, "NFN CODE")),
    _r("OFST020047", _S, _free_id(_SC_ID, "KOFIA SHARECLASS CODE")),
    _r("OFST020060", _S, "Names/OfficialName"),
    _r("OFST020070", _S, "Names/ShortName"),
    _r("OFST020540", _S, "Currency"),
    # -- static data
    _r("OFST020050", _S, "ShareClassType/Code"),
    _r("OFST020400", _S, "ShareClassType/EarningUse", DISTRIBUTION_POLICY),
    _r("OFST020560", _S, "InceptionDate"),
    _r("OFST020566", _S, "LiquidationDate"),
    _r("OFST023100", _S, "OpenToNewInvestorsFlag", INVESTMENT_STATUS_OPEN),
    _r("OFST020261", _S, "CurrencyHedgedFlag", CURRENCY_HEDGED_FLAG),
    _r("OFST020261", _S, "FundHedgingStrategy/HedgingStrategy", HEDGE_SHARECLASS),
    _r("OFST010630", _S, "IsLeveragedFlag", YES_NO),
    _r("OFST808500", _S, "PEA_EligibleFlag", YES_NO),
    _r("OFST400230", _S, "SubscriptionRestrictions/MinSubscriptionAmount/Amount[@ccy={OFST400240}]"),
    _r("OFST400220", _S, "SubscriptionRestrictions/MinSubscriptionShares"),
    _r(
        "OFST400260", _S, "SubscriptionRestrictions/MinSubscriptionAmountSubsequent/Amount[@ccy={OFST400240}]"
    ),
    _r("OFST400250", _S, "SubscriptionRestrictions/MinSubscriptionSharesSubsequent"),
    _r("OFST451155", _S, "HighWatermark/ExistingFlag", YES_NO),
    _r("OFST451160", _S, "HighWatermark/PeriodicalResetFlag", HWM_RESET),
    # -- fees charged to the share class as a percentage of its net assets (prospectus maxima)
    _r("OFST452010", _S, "Fees/Fee[Type=Management Fee]/Maximum", t.PCT100),
    _r("OFST452005", _S, "Fees/Fee[Type=Management Fee]/Minimum", t.PCT100),
    _r("OFST451042", _S, "Fees/Fee[Type=Custodian Fee]/Maximum", t.PCT100),
    _r("OFST451065", _S, "Fees/Fee[Type=Administration Fee]/Maximum", t.PCT100),
    _r("OFST452015", _S, "Fees/Fee[Type=All-in Fee]/Maximum", t.PCT100),
    _r("OFST454165", _S, "Fees/Fee[Type=Distribution Fee]/Maximum", t.PCT100),
    # -- transfer agent
    _r("OFST002700", _S, "TransferAgent/Name"),
    _r("OFST002705", _S, "TransferAgent/Identifiers/SwiftBIC"),
    _r("OFST002710", _S, "TransferAgent/Address/Country"),
    # -- listing (one record per listing)
    _r("OFST062030", _S, "MarketPlaces/MarketPlace[MarketIdentifierCode={OFST062030}]/MarketIdentifierCode"),
    _r("OFST062010", _S, "MarketPlaces/MarketPlace[MarketIdentifierCode={OFST062030}]/TradingCurrency"),
    # -- investors (one OFIN record per investor)
    _r("OFIN000010", _S, "Investors/Investor[InvestorID={OFIN000010}]/InvestorID"),
    _r("OFIN000130", _S, "Investors/Investor[InvestorID={OFIN000010}]/NumberOfShares"),
    _r("OFIN000410", _S, "Investors/Investor[InvestorID={OFIN000010}]/Date"),
]

_SHARECLASS_DYNAMIC_RULES: list[Rule] = [
    # -- price per share (single pricing: Valuation NAV is the official, unswung NAV)
    _r("OFDY000036", _S, f"{_PRICE}/NavDate"),
    _r("OFDY000010", _S, f"{_PRICE}/PriceCurrency"),
    _r(
        "OFST020540",
        _S,
        f"{_PRICE}/PriceCurrency",
        when=lambda row: _empty("OFDY000010")(row) and bool(row.get("OFDY000035") or row.get("OFDY000036")),
        when_text="OFDY000010 empty (openfunds default: share class currency) and a NAV is given",
        reverse_when=_never,
    ),
    _r("OFDY000035", _S, f"{_PRICE}/NavPrice"),
    _r(
        "OFDY000040",
        _S,
        f"{_PRICE}/OtherPrices/Price[PriceType=SWING]/NavPrice",
        when=lambda row: _SWING(row) and _same_date("OFDY000041", "OFDY000036")(row),
        when_text="OFST401003 = full/partial swing NAV and same date as OFDY000036",
    ),
    _r(
        "OFDY000020",
        _S,
        f"{_PRICE}/RedemptionPrice",
        when=_same_date("OFDY000021", "OFDY000036"),
        when_text="OFDY000021 empty or equal to OFDY000036",
    ),
    _r(
        "OFDY000025",
        _S,
        f"{_PRICE}/SubscriptionPrice",
        when=_same_date("OFDY000026", "OFDY000036"),
        when_text="OFDY000026 empty or equal to OFDY000036",
    ),
    # -- share class volume
    _r("OFDY000071", _S, f"{_TAV}/NavDate"),
    _r(
        "OFDY000076",
        _S,
        f"{_TAV}/NavDate",
        when=_empty("OFDY000071"),
        when_text="OFDY000071 empty",
        reverse_when=_never,
    ),
    _r("OFDY000070", _S, f"{_TAV}/TotalNetAssetValue/Amount[@ccy={{OFST020540}}]"),
    _r(
        "OFDY000075",
        _S,
        f"{_TAV}/SharesOutstanding",
        when=lambda row: _empty("OFDY000071")(row) or _same_date("OFDY000076", "OFDY000071")(row),
        when_text="OFDY000076 empty or equal to OFDY000071",
    ),
    # -- distribution (dividend per share)
    _r("OFDY005030", _S, f"{_DIST}/DividendStatus", DIVIDEND_STATUS),
    _r("OFDY005005", _S, f"{_DIST}/AnnouncementDate"),
    _r("OFDY005007", _S, f"{_DIST}/RecordDate"),
    _r("OFDY005010", _S, f"{_DIST}/ExDate"),
    _r("OFDY005015", _S, f"{_DIST}/PaymentDate"),
    _r("OFDY005000", _S, f"{_DIST}/PaymentCurrency"),
    _r("OFDY005020", _S, f"{_DIST}/GrossDividendAmount/PerShare/Amount[@ccy={{OFDY005000}}]"),
    _r("OFDY005022", _S, f"{_DIST}/NetDividendAmount/PerShare/Amount[@ccy={{OFDY005000}}]"),
]

# Registration and distribution per country (country-pattern fields OFST6030XX, …).
REGISTRATION_COUNTRIES = (
    *("AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU"),  # EU
    *("IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"),  # EU
    *("IS", "LI", "NO"),  # EEA
    *("CH", "GB", "HK", "SG", "TW", "CL", "PE", "US", "AU"),
)


def _registration_rules(cc: str) -> list[Rule]:
    reg = f"RegistrationCountries/RegistrationCountry[CountryCode={cc}]"
    legal, marketing = f"OFST6030{cc}", f"OFST6031{cc}"
    registered = field_is(legal, "yes", "res")
    distributed = field_is(marketing, "yes", "res")
    return [
        _r(legal, _S, f"{reg}/Status", REGISTRATION_STATUS),
        _r(f"OFST6010{cc}", _S, f"{reg}/StatusDate", when=registered, when_text=f"{legal} = yes/res"),
        # "no" plus a deregistration date: the share class was registered and no longer is
        _r(
            legal,
            _S,
            f"{reg}/Status",
            DEREGISTERED,
            when=lambda row: bool(row.get(f"OFST6011{cc}", "").strip()),
            when_text=f"OFST6011{cc} given",
            reverse_when=_always,
        ),
        _r(f"OFST6011{cc}", _S, f"{reg}/StatusDate", when=field_is(legal, "no"), when_text=f"{legal} = no"),
        _r(marketing, _S, f"{reg}/MarketingDistributionStatus", REGISTRATION_STATUS),
        _r(
            f"OFST6020{cc}",
            _S,
            f"{reg}/MarketingDistributionStatusDate",
            when=distributed,
            when_text=f"{marketing} = yes/res",
        ),
        _r(
            marketing,
            _S,
            f"{reg}/MarketingDistributionStatus",
            DEREGISTERED,
            when=lambda row: bool(row.get(f"OFST6021{cc}", "").strip()),
            when_text=f"OFST6021{cc} given",
            reverse_when=_always,
        ),
        _r(
            f"OFST6021{cc}",
            _S,
            f"{reg}/MarketingDistributionStatusDate",
            when=field_is(marketing, "no"),
            when_text=f"{marketing} = no",
        ),
    ]


STATIC_RULES: list[Rule] = [
    *_FUND_RULES,
    *_FUND_DYNAMIC_RULES,
    *_SHARECLASS_RULES,
    *_SHARECLASS_DYNAMIC_RULES,
    *(rule for cc in REGISTRATION_COUNTRIES for rule in _registration_rules(cc)),
]

_FEE_TYPES = ("Management Fee", "Custodian Fee", "Administration Fee", "All-in Fee", "Distribution Fee")

# Constant mandatory children, added when the parent exists but the child is missing.
DEFAULTS: list[tuple[str, str, str, str]] = [
    (_S, _PRICE, "ActionCode", "C"),
    (_S, _PRICE, "PriceNature", "OFFICIAL"),
    (_S, _TAV, "TotalAssetNature", "OFFICIAL"),
    (_F, _FUND_TAV, "TotalAssetNature", "OFFICIAL"),
    (_S, _DIST, "ActionCode", "C"),
    # PeriodicalResetFlag only comes from a "high water mark, (no) reset" value
    (_S, "HighWatermark", "ExistingFlag", "true"),
    *((_S, f"Fees/Fee[Type={fee}]", "PayReceive", "P") for fee in _FEE_TYPES),
]
