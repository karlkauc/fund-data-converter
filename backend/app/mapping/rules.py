"""TPT field ↔ FundsXML path rules.

Two rule sets:

* **block** – the FundsXML Solvency II TPT block
  ``RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7``.
  It mirrors the template nearly 1:1 and is the lossless store.
* **core** – the regular FundsXML structures: ``Funds/Fund`` (identifiers,
  name, NAV), ``Portfolio/Positions/Position`` (holding values) and
  ``AssetMasterData/Asset`` (instrument master data incl. AssetDetails by
  instrument type, derived from the CIC code).

Rule contexts (the node a path is relative to):

=================  ==========================================================
``tpt_portfolio``  TripartiteTemplateSolvencyII_V7/Portfolio
``tpt_position``   …/Portfolio/Positions/Position
``shareclass``     Fund/SingleFund/ShareClasses/ShareClass
``sc_nav``         …/ShareClass/TotalAssetValues/TotalAssetValue
``sc_price``       …/ShareClass/Prices/Price
``fund``           Funds/Fund
``fund_info``      Funds/Fund – static data shared by all its share classes
``nav``            Fund/FundDynamicData/TotalAssetValues/TotalAssetValue
``control``        ControlData
``position``       …/Portfolios/Portfolio/Positions/Position
``asset``          AssetMasterData/Asset
=================  ==========================================================

A TPT portfolio is a share class (field 1 = its ISIN). Its positions come from
``ShareClass/Portfolios``, else from the fund portfolio in ``FundDynamicData``.
``fund`` and ``nav`` are only read for a fund without share classes; written
are just the mandatory fund name and currency.

``read_only`` rules only apply to FundsXML → TPT: alternative places other
producers use for a value (``AssetDetails/*/Issuer``, ``CommercialPaper``, …).

Paths may contain ``{key}`` placeholders that are replaced with the value of
another TPT field of the same row (e.g. the currency in ``Amount[@ccy={4}]``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.mapping import transforms as t
from app.mapping.transforms import Transform, asset_type, cic_category, position_element

Condition = Callable[[dict[str, str]], bool]

PORTFOLIO_CONTEXTS = (
    "tpt_portfolio",
    "shareclass",
    "sc_nav",
    "sc_price",
    "fund",
    "fund_info",
    "nav",
    "control",
)
POSITION_CONTEXTS = ("tpt_position", "position", "asset")


@dataclass(frozen=True)
class Rule:
    field: str
    ctx: str
    path: str
    transform: Transform = t.IDENTITY
    when: Condition | None = None
    when_text: str = ""  # human-readable condition for the mapping table
    # Reverse direction (FundsXML → TPT): condition evaluated on the values read so far
    # (defaults to ``when``) and further fields to fill when this rule matches.
    reverse_when: Condition | None = None
    reverse_sets: tuple[tuple[str, str], ...] = ()
    read_only: bool = False  # FundsXML → TPT only

    @property
    def is_block(self) -> bool:
        return self.ctx.startswith("tpt_")

    def applies(self, row: dict[str, str]) -> bool:
        return self.when is None or self.when(row)

    def applies_reverse(self, row: dict[str, str]) -> bool:
        cond = self.reverse_when or self.when
        return cond is None or cond(row)

    def resolve(self, row: dict[str, str]) -> str | None:
        """Path with placeholders filled from ``row``; None if one is empty."""
        path = self.path
        while "{" in path:
            start = path.index("{")
            end = path.index("}", start)
            value = row.get(path[start + 1 : end], "")
            if not value:
                return None
            path = path[:start] + value + path[end + 1 :]
        return path


def _r(
    field: str,
    ctx: str,
    path: str,
    transform: Transform = t.IDENTITY,
    when: Condition | None = None,
    when_text: str = "",
    **kw,
) -> Rule:
    return Rule(field, ctx, path, transform, when, when_text, **kw)


def _ro(field: str, ctx: str, path: str, transform: Transform = t.IDENTITY, **kw) -> Rule:
    return Rule(field, ctx, path, transform, when_text=kw.pop("when_text", "read only"), read_only=True, **kw)


def _lei(code: str, kind: str, ctx: str, path: str) -> Rule:
    """A read-only LEI source that also sets the code type (1 = LEI)."""
    return _ro(
        code,
        ctx,
        path,
        reverse_when=field_is(kind, "", "1"),
        reverse_sets=((kind, "1"),),
        when_text=f"read only, sets {kind} = 1",
    )


def field_is(key: str, *values: str) -> Condition:
    vals = {v.lower() for v in values}
    return lambda row: row.get(key, "").strip().lower() in vals


def asset_types(*types: str) -> Condition:
    wanted = set(types)
    return lambda row: asset_type(row.get("12", "")) in wanted


def category(*cats: str) -> Condition:
    wanted = set(cats)
    return lambda row: cic_category(row.get("12", "")) in wanted


# ---------------------------------------------------------------------------
# TPT block (TripartiteTemplateSolvencyII_V7)
# ---------------------------------------------------------------------------

_P, _Q = "tpt_portfolio", "tpt_position"
_QRT = "QRTPortfolioInformation"
_IR = "InterestRateInstrumentCharacteristics"
_UND = "DerivativeOrConvertible/UnderlyingInstrument"

BLOCK_RULES: list[Rule] = [
    _r("1000", _P, "TPTVersion", t.TPT_VERSION),
    _r("1", _P, "PortfolioID/Code"),
    _r("2", _P, "PortfolioID/CodificationSystem"),
    _r("3", _P, "PortfolioName"),
    _r("4", _P, "PortfolioCurrency"),
    _r("5", _P, "TotalNetAssets"),
    _r("6", _P, "ValuationDate"),
    _r("7", _P, "ReportingDate"),
    _r("8", _P, "ShareClass/SharePrice"),
    _r("8b", _P, "ShareClass/TotalNumberOfShares"),
    _r("9", _P, "CashPercentage"),
    _r("10", _P, "PortfolioModifiedDuration"),
    _r("11", _P, "CompleteSCRDelivery"),
    _r("117", _P, f"{_QRT}/FundIssuer/Name"),
    _r("115", _P, f"{_QRT}/FundIssuer/Code"),
    _r("116", _P, f"{_QRT}/FundIssuer/CodeType"),
    _r("118", _P, f"{_QRT}/FundIssuer/EconomicSector"),
    _r("122", _P, f"{_QRT}/FundIssuer/Country"),
    _r("121", _P, f"{_QRT}/FundIssuerGroup/Name"),
    _r("119", _P, f"{_QRT}/FundIssuerGroup/Code"),
    _r("120", _P, f"{_QRT}/FundIssuerGroup/CodeType"),
    _r("123", _P, f"{_QRT}/FundCIC"),
    _r("123a", _P, f"{_QRT}/FundCustodianCountry"),
    _r("133", _P, f"{_QRT}/FundCustodianName"),
    _r("140", _P, f"{_QRT}/CustodianIdentificationCode"),
    _r("141", _P, f"{_QRT}/TypeOfCustodianIdentificationCode"),
    _r("124", _P, f"{_QRT}/Duration"),
    # positions
    _r("12", _Q, "InstrumentCIC"),
    _r("13", _Q, "EconomicArea"),
    _r("14", _Q, "InstrumentCode/Code"),
    _r("15", _Q, "InstrumentCode/CodificationSystem"),
    _r("16", _Q, "GroupID"),
    _r("17", _Q, "InstrumentName"),
    _r("18", _Q, "Valuation/Quantity"),
    _r("19", _Q, "Valuation/TotalNominalValueQC"),
    _r("20", _Q, "Valuation/ContractSize"),
    _r("21", _Q, "Valuation/QuotationCurrency"),
    _r("22", _Q, "Valuation/MarketValueQC"),
    _r("23", _Q, "Valuation/CleanValueQC"),
    _r("125", _Q, "Valuation/AccruedIncomeQC"),
    _r("24", _Q, "Valuation/MarketValuePC"),
    _r("25", _Q, "Valuation/CleanValuePC"),
    _r("126", _Q, "Valuation/AccruedIncomePC"),
    _r("26", _Q, "Valuation/PositionWeight"),
    _r("27", _Q, "Valuation/MarketExposureQC"),
    _r("28", _Q, "Valuation/MarketExposurePC"),
    _r("29", _Q, "Valuation/MarketExposureUC"),
    _r("30", _Q, "Valuation/MarketExposureWeight"),
    _r("31", _Q, "Valuation/MarketExposureUCWeight"),
    _r("32", _Q, f"{_IR}/RateType"),
    _r("33", _Q, f"{_IR}/CouponRate", t.PCT100),
    _r("34", _Q, f"{_IR}/VariableRate/IndexID/Code"),
    _r("35", _Q, f"{_IR}/VariableRate/IndexID/CodificationSystem"),
    _r("36", _Q, f"{_IR}/VariableRate/IndexName"),
    _r("37", _Q, f"{_IR}/VariableRate/Margin", t.PCT100),
    _r("38", _Q, f"{_IR}/CouponFrequency"),
    _r("63", _Q, f"{_IR}/EffectiveDateOfInstrument"),
    _r("39", _Q, f"{_IR}/Redemption/MaturityDate"),
    _r("143", _Q, f"{_IR}/Redemption/MaturityDateExpected"),
    _r("40", _Q, f"{_IR}/Redemption/Type"),
    _r("41", _Q, f"{_IR}/Redemption/Rate"),
    _r("146", _Q, f"{_IR}/Redemption/PIK"),
    _r("42", _Q, f"{_IR}/EmbeddedOption/CallPutType"),
    _r("43", _Q, f"{_IR}/EmbeddedOption/CallPutDate"),
    _r("44", _Q, f"{_IR}/EmbeddedOption/OptionDirection"),
    _r("45", _Q, f"{_IR}/EmbeddedOption/StrikePrice"),
    _r("129", _Q, f"{_IR}/ValuationYieldCurve/Yield"),
    _r("130", _Q, f"{_IR}/ValuationYieldCurve/Spread"),
    _r("46", _Q, "CreditRiskData/InstrumentIssuer/Name"),
    _r("47", _Q, "CreditRiskData/InstrumentIssuer/Code"),
    _r("48", _Q, "CreditRiskData/InstrumentIssuer/CodeType"),
    _r("49", _Q, "CreditRiskData/IssuerGroup/Name"),
    _r("50", _Q, "CreditRiskData/IssuerGroup/Code"),
    _r("51", _Q, "CreditRiskData/IssuerGroup/CodeType"),
    _r("52", _Q, "CreditRiskData/IssuerCountry"),
    _r("53", _Q, "CreditRiskData/EconomicArea"),
    _r("57", _Q, "CreditRiskData/StateGuarantee"),
    _r("59", _Q, "CreditRiskData/CreditQualityStep"),
    _r("54", _Q, "CreditRiskData/EconomicSector"),
    _r("148", _Q, "CreditRiskData/EconomicSectorNACE2.1"),
    _r("55", _Q, "CreditRiskData/Covered"),
    _r("56", _Q, "Securitisation/Securitised", t.SECURITISED_V7),
    _r("58b", _Q, "Securitisation/TrancheLevel"),
    _r("58", _Q, "SubordinatedDebt"),
    _r("65", _Q, "HedgingRolling"),
    _r("60", _Q, "DerivativeOrConvertible/OptionCharacteristics/CallPutType"),
    _r("61", _Q, "DerivativeOrConvertible/OptionCharacteristics/StrikePrice"),
    _r("62", _Q, "DerivativeOrConvertible/OptionCharacteristics/ConversionRatio"),
    _r("64", _Q, "DerivativeOrConvertible/OptionCharacteristics/ExerciseType"),
    _r("127", _Q, "DerivativeOrConvertible/OptionCharacteristics/Convertible/BondFloor"),
    _r("128", _Q, "DerivativeOrConvertible/OptionCharacteristics/Convertible/OptionPremium"),
    _r("67", _Q, f"{_UND}/InstrumentCIC"),
    _r("68", _Q, f"{_UND}/InstrumentCode/Code"),
    _r("69", _Q, f"{_UND}/InstrumentCode/CodificationSystem"),
    _r("70", _Q, f"{_UND}/InstrumentName"),
    _r("71", _Q, f"{_UND}/Valuation/Currency"),
    _r("72", _Q, f"{_UND}/Valuation/MarketPrice"),
    _r("73", _Q, f"{_UND}/Valuation/Country"),
    _r("74", _Q, f"{_UND}/Valuation/EconomicArea"),
    _r("75", _Q, f"{_UND}/Coupon/CouponRate", t.PCT100),
    _r("76", _Q, f"{_UND}/Coupon/CouponFrequency"),
    _r("77", _Q, f"{_UND}/Redemption/MaturityDate"),
    _r("78", _Q, f"{_UND}/Redemption/Type"),
    _r("79", _Q, f"{_UND}/Redemption/Rate"),
    _r("80", _Q, f"{_UND}/CreditRiskData/InstrumentIssuer/Name"),
    _r("81", _Q, f"{_UND}/CreditRiskData/InstrumentIssuer/Code"),
    _r("82", _Q, f"{_UND}/CreditRiskData/InstrumentIssuer/CodeType"),
    _r("83", _Q, f"{_UND}/CreditRiskData/IssuerGroup/Name"),
    _r("84", _Q, f"{_UND}/CreditRiskData/IssuerGroup/Code"),
    _r("85", _Q, f"{_UND}/CreditRiskData/IssuerGroup/CodeType"),
    _r("86", _Q, f"{_UND}/CreditRiskData/IssuerCountry"),
    _r("87", _Q, f"{_UND}/CreditRiskData/EconomicArea"),
    _r("88", _Q, f"{_UND}/CreditRiskData/StateGuarantee"),
    _r("89", _Q, f"{_UND}/CreditRiskData/CreditQualityStep"),
    _r("90", _Q, "Analytics/ModifiedDurationToMaturity"),
    _r("91", _Q, "Analytics/ModifiedDurationToCall"),
    _r("92", _Q, "Analytics/CreditSensitivity"),
    _r("93", _Q, "Analytics/Delta"),
    _r("94", _Q, "Analytics/Convexity"),
    _r("94b", _Q, "Analytics/Vega"),
    _r("144", _Q, "Analytics/ModifiedDurationToMaturityDateExpected"),
    _r("145", _Q, "Analytics/CreditSensitivityExpected"),
    _r("95", _Q, "LookThroughIdentifier"),
    _r("97", _Q, "ContributionToSCR/MktIntUp"),
    _r("98", _Q, "ContributionToSCR/MktIntDown"),
    _r("99", _Q, "ContributionToSCR/MktEqGlobal"),
    _r("100", _Q, "ContributionToSCR/MktEqOther"),
    _r("101", _Q, "ContributionToSCR/MktProp"),
    _r("102", _Q, "ContributionToSCR/MktSpread/Bonds"),
    _r("103", _Q, "ContributionToSCR/MktSpread/Structured"),
    _r("104", _Q, "ContributionToSCR/MktSpread/DerivativesUp"),
    _r("105", _Q, "ContributionToSCR/MktSpread/DerivativesDown"),
    _r("105a", _Q, "ContributionToSCR/MktFXUp"),
    _r("105b", _Q, "ContributionToSCR/MktFXDown"),
    _r("106", _Q, "QRTPositionInformation/CollateralisedAsset"),
    _r("107", _Q, "QRTPositionInformation/PlaceOfDeposit"),
    _r("108", _Q, "QRTPositionInformation/Participation"),
    _r("110", _Q, "QRTPositionInformation/ValorisationMethod"),
    _r("111", _Q, "QRTPositionInformation/AcquisitionValue"),
    _r("112", _Q, "QRTPositionInformation/CounterpartyRating/RatingValue"),
    _r("113", _Q, "QRTPositionInformation/CounterpartyRating/RatingAgency"),
    _r("131", _Q, "QRTPositionInformation/UnderlyingAssetCategory"),
    _r("132", _Q, "AdditionalInformation/InfrastructureInvestment"),
    _r("147", _Q, "AdditionalInformation/InfrastructureInvestmentAdditionalQRT"),
    _r("134", _Q, "AdditionalInformation/Type1PrivateEquityPortfolioEligibility"),
    _r("135", _Q, "AdditionalInformation/Type1PrivateEquityIssuerBeta"),
    _r("137", _Q, "AdditionalInformation/Counterparty_sector"),
    _r("138", _Q, "AdditionalInformation/CollateralEligibility"),
    _r("139", _Q, "AdditionalInformation/CollateralMarketValuationInPortfolioCurrency"),
    _r("142", _Q, "AdditionalInformation/BailInRule"),
]

# ---------------------------------------------------------------------------
# Core FundsXML
# ---------------------------------------------------------------------------

# TPT identification code types (fields 2, 15) → element in IdentifiersType.
IDENTIFIER_ELEMENTS = {
    "1": "ISIN",
    "2": "CUSIP",
    "3": "SEDOL",
    "4": "GermanWKN",
    "5": "Bloomberg/Ticker",
    "6": "Bloomberg/BBGID",
    "7": "ReutersRIC",
    "8": "FIGI",
}


def _identifier_rules(code: str, kind: str, ctx: str, base: str, note: str = "") -> list[Rule]:
    targets = [(type_code, f"{base}/{element}") for type_code, element in IDENTIFIER_ELEMENTS.items()]
    targets += [(tc, f"{base}/OtherID[@FreeType=TPT code type {tc}]") for tc in ("9", "99")]
    return [
        Rule(
            code,
            ctx,
            path,
            when=field_is(kind, type_code),
            when_text=f"{kind} = {type_code}{note}",
            reverse_when=field_is(kind, "", type_code),
            reverse_sets=((kind, type_code),),
        )
        for type_code, path in targets
    ]


_NO_CLASSES = ", fund without share classes"

# ControlData written by TPT → FundsXML when the TPT names no fund issuer; never read back as one.
PLACEHOLDER_SUPPLIER = "Fund Data Converter"
# What files written before the rename (2026-10) carry there; recognised the same way.
PLACEHOLDER_SUPPLIERS = frozenset({PLACEHOLDER_SUPPLIER, "TPT to FundsXML Converter"})
PLACEHOLDER_COUNTRY = "XX"

# Instrument types with an issuer resp. a counterparty in AssetDetails (beyond the bidirectional rules).
_ISSUED = (
    "Bond",
    "Equity",
    "ShareClass",
    "Certificate",
    "CommercialPaper",
    "REIT",
    "Right",
    "Warrant",
    "PrivateEquity",
)
_COUNTERPARTY = (
    "Account",
    "CallMoney",
    "FixedTimeDeposit",
    "Loan",
    "FXForward",
    "Swap",
    "Future",
    "Option",
    "Repo",
)


def _internal_id(ctx: str, code: str = "14", kind: str = "15", path: str = "Identifiers/OtherID") -> Rule:
    """Any other identifier, e.g. an internal code, as type 99 (code attributed by the undertaking)."""
    return _ro(
        code,
        ctx,
        path,
        reverse_when=field_is(kind, ""),
        reverse_sets=((kind, "99"),),
        when_text=f"read only, no other identifier; sets {kind} = 99",
    )


def _position_fallbacks() -> list[Rule]:
    out = [_ro("18", "position", f"{kind}/Units") for kind in ("REIT", "Right", "Warrant")]
    out.append(_ro("19", "position", "CommercialPaper/Nominal"))
    # The quantity and value of the position element the source has, also when its CIC points
    # to another one (an equity classified as bond): otherwise the instrument comes back without.
    for kind, quantity in (
        ("Equity", "Units"),
        ("ShareClass", "Shares"),
        ("Certificate", "Units"),
        ("Option", "Contracts"),
        ("Future", "Contracts"),
    ):
        out.append(_ro("18", "position", f"{kind}/{quantity}", when_text="read only, CIC of another kind"))
    out.append(_ro("19", "position", "Bond/Nominal", when_text="read only, CIC of another kind"))
    not_equity = lambda r: not _EQ_LIKE(r)  # noqa: E731
    for field, ccy in (("25", "4"), ("23", "21")):
        out.append(
            _ro(
                field,
                "position",
                f"Equity/MarketValue/Amount[@ccy={{{ccy}}}]",
                when=not_equity,
                when_text="read only, equity with a CIC of another kind: clean = market value",
            )
        )
    # clean value and accrued interest: TotalValue = MarketValue + interest
    for kind, interest in (
        ("Bond", "InterestClaimGross"),
        ("CommercialPaper", "InterestClaimGross"),
        ("Account", "Interests"),
        ("CallMoney", "Interests"),
        ("FixedTimeDeposit", "Interests"),
        ("Loan", "InterestAccruals"),
    ):
        if kind == "Bond":
            continue  # the bond rules for 23/25/125/126 are bidirectional
        out.append(_ro("25", "position", f"{kind}/MarketValue/Amount[@ccy={{4}}]"))
        out.append(_ro("126", "position", f"{kind}/{interest}/Amount[@ccy={{4}}]"))
        out.append(_ro("23", "position", f"{kind}/MarketValue/Amount[@ccy={{21}}]"))
        out.append(_ro("125", "position", f"{kind}/{interest}/Amount[@ccy={{21}}]"))
    return out


def _asset_fallbacks() -> list[Rule]:
    out = []
    for role, kinds in (("Issuer", _ISSUED), ("Counterparty", _COUNTERPARTY)):
        for kind in kinds:
            base = f"AssetDetails/{kind}/{role}"
            out += [
                _ro("46", "asset", f"{base}/Name"),
                _lei("47", "48", "asset", f"{base}/Identifiers/LEI"),
                _ro("52", "asset", f"{base}/Address/Country"),
            ]
    out.append(_ro("39", "asset", "AssetDetails/*/MaturityDate"))
    # reference rate of a floater
    for rule in _identifier_rules("34", "35", "asset", "AssetDetails/Bond/Coupon/BaseIndex"):
        out.append(replace(rule, read_only=True, when_text=f"read only, {rule.when_text}"))
    out.append(_internal_id("asset", "34", "35", "AssetDetails/Bond/Coupon/BaseIndex/OtherID"))
    out.append(_ro("148", "asset", "Classifications/Classification[UnlistedGroup=NACE Rev 2.1]/Value"))
    return out


_BOND = asset_types("BO")


def _foreign_bond(row) -> bool:
    """A bond quoted in another currency than the portfolio's: its amounts exist in both."""
    return _BOND(row) and bool(row.get("21")) and row.get("21") != row.get("4")


_EQ_LIKE = asset_types("EQ", "PE")

CORE_RULES: list[Rule] = [
    # Share class: the TPT portfolio
    *_identifier_rules("1", "2", "shareclass", "Identifiers"),
    _r("3", "shareclass", "Names/OfficialName"),
    _r("4", "shareclass", "Currency"),
    # NAV and price of the share class on the valuation date
    _r("6", "sc_nav", "NavDate"),
    _r("5", "sc_nav", "TotalNetAssetValue/Amount[@ccy={4}]"),
    _r("8b", "sc_nav", "SharesOutstanding"),
    _r("6", "sc_price", "NavDate"),
    _r("4", "sc_price", "PriceCurrency"),
    _r("8", "sc_price", "NavPrice"),
    # Fund without share classes (read only); name and currency are written as well
    *_identifier_rules("1", "2", "fund", "Identifiers", _NO_CLASSES),
    _r("3", "fund", "Names/OfficialName"),
    _r("4", "fund", "Currency"),
    _r("6", "nav", "NavDate", when_text=_NO_CLASSES[2:]),
    _r("5", "nav", "TotalNetAssetValue/Amount[@ccy={4}]", when_text=_NO_CLASSES[2:]),
    _r("8b", "nav", "SharesOutstanding", when_text=_NO_CLASSES[2:]),
    # Fund static data, shared by the share classes
    _r("123", "fund_info", "FundStaticData/Classifications/Classification[ListedGroup=CIC]/Value"),
    _ro("117", "fund_info", "FundStaticData/InvestmentCompany/Name"),
    _lei("115", "116", "fund_info", "FundStaticData/InvestmentCompany/Identifiers/LEI"),
    _ro("122", "fund_info", "FundStaticData/InvestmentCompany/Address/Country"),
    _ro("133", "fund_info", "FundStaticData/Custodian/Name"),
    _lei("140", "141", "fund_info", "FundStaticData/Custodian/Identifiers/LEI"),
    _ro("123a", "fund_info", "FundStaticData/Custodian/Address/Country"),
    _ro("7", "control", "ContentDate"),
    # Last resort for the fund issuer: the sender of the document (see PLACEHOLDER_SUPPLIER).
    _ro("117", "control", "DataSupplier/Name"),
    _ro("122", "control", "DataSupplier/SystemCountry"),
    # Position
    *_identifier_rules("14", "15", "position", "Identifiers"),
    _internal_id("position"),
    # Last resort, e.g. cash and fees with an empty OtherID: the sender's own key of the asset.
    _internal_id("position", path="UniqueID"),
    _r("21", "position", "Currency"),
    _r("22", "position", "TotalValue/Amount[@ccy={21}]"),
    _r("24", "position", "TotalValue/Amount[@ccy={4}]"),
    _r("26", "position", "TotalPercentage", t.PCT100),
    _r("19", "position", "Bond/Nominal", when=_BOND, when_text="bond (CIC x1, x2, x5, x6)"),
    _r(
        "18",
        "position",
        "Bond/Nominal",
        t.STAND_IN,
        when=lambda r: _BOND(r) and not r.get("19"),
        when_text="bond without nominal amount (19)",
    ),
    _r("25", "position", "Bond/MarketValue/Amount[@ccy={4}]", when=_BOND, when_text="bond"),
    _r("126", "position", "Bond/InterestClaimGross/Amount[@ccy={4}]", when=_BOND, when_text="bond"),
    _r(
        "23",
        "position",
        "Bond/MarketValue/Amount[@ccy={21}]",
        when=_foreign_bond,
        when_text="bond quoted in another currency than the portfolio",
    ),
    _r(
        "125",
        "position",
        "Bond/InterestClaimGross/Amount[@ccy={21}]",
        when=_foreign_bond,
        when_text="bond quoted in another currency than the portfolio",
    ),
    _r("18", "position", "Equity/Units", when=_EQ_LIKE, when_text="equity (CIC x3)"),
    _r(
        "24",
        "position",
        "Equity/MarketValue/Amount[@ccy={4}]",
        when=lambda r: position_element(r) == "Equity",
        reverse_when=_EQ_LIKE,
        when_text="equity (private equity without quantity: PrivateEquity)",
    ),
    _r("18", "position", "ShareClass/Shares", when=asset_types("SC"), when_text="fund share (CIC x4)"),
    _r("18", "position", "Certificate/Units", when=asset_types("CE"), when_text="other (CIC x0)"),
    _r("18", "position", "Option/Contracts", when=asset_types("OP"), when_text="option (CIC xB, xC)"),
    _r("18", "position", "Future/Contracts", when=asset_types("FU"), when_text="future (CIC xA, xE)"),
    _r(
        "24",
        "position",
        "Account/MarketValue/Amount[@ccy={4}]",
        when=asset_types("AC"),
        when_text="cash (CIC x71, x72)",
    ),
    _r(
        "24",
        "position",
        "FixedTimeDeposit/MarketValue/Amount[@ccy={4}]",
        when=asset_types("FT"),
        when_text="deposit (CIC x73–x75)",
    ),
    _r(
        "24",
        "position",
        "Loan/MarketValue/Amount[@ccy={4}]",
        when=asset_types("LO"),
        when_text="loan (CIC x8)",
    ),
    _r(
        "24",
        "position",
        "RealEstate/MarketValue/Amount[@ccy={4}]",
        when=asset_types("RE"),
        when_text="property (CIC x9)",
    ),
    *_position_fallbacks(),
    _r("12", "position", "Swap", t.const(""), when=asset_types("SW"), when_text="swap (CIC xD, xF)"),
    _r("12", "position", "FXForward", t.const(""), when=asset_types("FX"), when_text="FX forward (CIC xE2)"),
    # Asset master data
    *_identifier_rules("14", "15", "asset", "Identifiers"),
    _internal_id("asset"),
    _r("21", "asset", "Currency"),
    _r("52", "asset", "Country"),
    _r("17", "asset", "Name"),
    _r("12", "asset", "Classifications/Classification[ListedGroup=CIC]/Value"),
    _r("12", "asset", "AssetType", t.ASSET_TYPE),
    # bonds
    _r("12", "asset", "AssetDetails/Bond/ConvertibleFlag", t.CONVERTIBLE_T, when=_BOND, when_text="bond"),
    _r("46", "asset", "AssetDetails/Bond/Issuer/Name", when=_BOND, when_text="bond"),
    _r(
        "47",
        "asset",
        "AssetDetails/Bond/Issuer/Identifiers/LEI",
        when=lambda r: _BOND(r) and r.get("48") == "1",
        when_text="bond, 48 = 1 (LEI)",
    ),
    _r("52", "asset", "AssetDetails/Bond/Issuer/BusinessCountry", when=_BOND, when_text="bond"),
    _r("39", "asset", "AssetDetails/Bond/MaturityDate", when=_BOND, when_text="bond"),
    _r(
        "38",
        "asset",
        "AssetDetails/Bond/Coupon/PaymentFrequency",
        t.COUPON_FREQUENCY,
        when=_BOND,
        when_text="bond",
    ),
    _r("32", "asset", "AssetDetails/Bond/Coupon/Type", t.RATE_TYPE, when=_BOND, when_text="bond"),
    _r("33", "asset", "AssetDetails/Bond/Coupon/InterestRate", t.PCT100, when=_BOND, when_text="bond"),
    _r("37", "asset", "AssetDetails/Bond/Coupon/OffsetBPS", t.BPS, when=_BOND, when_text="bond"),
    _r("41", "asset", "AssetDetails/Bond/RedemptionRate", t.PCT100, when=_BOND, when_text="bond"),
    _r("40", "asset", "AssetDetails/Bond/Redemption/Type", t.REDEMPTION_TYPE, when=_BOND, when_text="bond"),
    _r("43", "asset", "AssetDetails/Bond/Redemption/OptionDate", when=_BOND, when_text="bond"),
    _r(
        "44",
        "asset",
        "AssetDetails/Bond/Redemption/OptionDirection",
        t.OPTION_DIRECTION,
        when=_BOND,
        when_text="bond",
    ),
    _r(
        "45",
        "asset",
        "AssetDetails/Bond/Redemption/OptionStrikePrice",
        t.PCT100,
        when=_BOND,
        when_text="bond",
    ),
    _r("33", "asset", "AssetDetails/Bond/InterestRate", t.PCT100, when=_BOND, when_text="bond"),
    _ro(
        "33",
        "asset",
        "AssetDetails/Bond/Coupon/Type",
        t.ZERO_COUPON_RATE,
        when_text="read only: zero coupon → 0",
    ),
    _r("63", "asset", "AssetDetails/Bond/InterestsStartDate", when=_BOND, when_text="bond"),
    _r(
        "62",
        "asset",
        "AssetDetails/Bond/ConvertibleBond/ConversionRatio",
        when=lambda r: _BOND(r) and cic_category(r.get("12", "")) == "2" and r.get("12", "")[3:4] == "2",
        when_text="convertible bond (CIC x22)",
    ),
    # equities and fund shares
    _r("46", "asset", "AssetDetails/Equity/Issuer/Name", when=_EQ_LIKE, when_text="equity"),
    _r(
        "47",
        "asset",
        "AssetDetails/Equity/Issuer/Identifiers/LEI",
        when=lambda r: _EQ_LIKE(r) and r.get("48") == "1",
        when_text="equity, 48 = 1 (LEI)",
    ),
    _r("52", "asset", "AssetDetails/Equity/Issuer/BusinessCountry", when=_EQ_LIKE, when_text="equity"),
    _r("46", "asset", "AssetDetails/ShareClass/Issuer/Name", when=asset_types("SC"), when_text="fund share"),
    _r(
        "47",
        "asset",
        "AssetDetails/ShareClass/Issuer/Identifiers/LEI",
        when=lambda r: asset_types("SC")(r) and r.get("48") == "1",
        when_text="fund share, 48 = 1 (LEI)",
    ),
    _r(
        "52",
        "asset",
        "AssetDetails/ShareClass/Issuer/BusinessCountry",
        when=asset_types("SC"),
        when_text="fund share",
    ),
    # cash accounts
    _r("46", "asset", "AssetDetails/Account/Counterparty/Name", when=asset_types("AC"), when_text="cash"),
    _r(
        "47",
        "asset",
        "AssetDetails/Account/Counterparty/Identifiers/LEI",
        when=lambda r: asset_types("AC")(r) and r.get("48") == "1",
        when_text="cash, 48 = 1 (LEI)",
    ),
    # futures
    _r(
        "12", "asset", "AssetDetails/Future/Type", t.FUTURE_TYPE_T, when=asset_types("FU"), when_text="future"
    ),
    _r("20", "asset", "AssetDetails/Future/ContractSize", when=asset_types("FU"), when_text="future"),
    _r("39", "asset", "AssetDetails/Future/MaturityDate", when=asset_types("FU"), when_text="future"),
    # options
    _r(
        "12", "asset", "AssetDetails/Option/Type", t.OPTION_TYPE_T, when=asset_types("OP"), when_text="option"
    ),
    _r("20", "asset", "AssetDetails/Option/ContractSize", when=asset_types("OP"), when_text="option"),
    _r("39", "asset", "AssetDetails/Option/MaturityDate", when=asset_types("OP"), when_text="option"),
    _r(
        "12",
        "asset",
        "AssetDetails/Option/CallPutIndicator",
        t.CALL_PUT_T,
        when=asset_types("OP"),
        when_text="option",
    ),
    _r(
        "61",
        "asset",
        "AssetDetails/Option/StrikePrice/Amount[@ccy={21}]",
        when=asset_types("OP"),
        when_text="option",
    ),
    # swaps
    _r("12", "asset", "AssetDetails/Swap/Type", t.SWAP_TYPE_T, when=asset_types("SW"), when_text="swap"),
    _r("39", "asset", "AssetDetails/Swap/MaturityDate", when=asset_types("SW"), when_text="swap"),
    _r("46", "asset", "AssetDetails/Swap/Counterparty/Name", when=asset_types("SW"), when_text="swap"),
    _r(
        "47",
        "asset",
        "AssetDetails/Swap/Counterparty/Identifiers/LEI",
        when=lambda r: asset_types("SW")(r) and r.get("48") == "1",
        when_text="swap, 48 = 1 (LEI)",
    ),
    *_asset_fallbacks(),
]

ALL_RULES = BLOCK_RULES + CORE_RULES


def rules_for(ctx: str) -> list[Rule]:
    return [r for r in ALL_RULES if r.ctx == ctx]


# Fields written once per portfolio (from its first row).
PORTFOLIO_FIELDS = {r.field for r in ALL_RULES if r.ctx in PORTFOLIO_CONTEXTS}
ASSET_FIELDS = {r.field for r in CORE_RULES if r.ctx == "asset"}
