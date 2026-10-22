"""Value transforms between TPT and FundsXML, each with its inverse.

A transform's ``to_xml`` returns ``(value, lossless)``; ``lossless=False``
means the original TPT value cannot be restored from the XML value, so the
converter also keeps it as a custom attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.model.xmltree import format_decimal, parse_decimal
from app.spec.catalog import VERSION_LABELS


@dataclass(frozen=True)
class Transform:
    name: str
    to_xml: Callable[[str, dict[str, str]], tuple[str | None, bool]]
    from_xml: Callable[[str, dict[str, str]], str | None]
    note: str = ""


def _identity_to(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
    return v, True


def _identity_from(v: str, _ctx: dict[str, str]) -> str | None:
    return v


IDENTITY = Transform("identity", _identity_to, _identity_from)
# A value written where the schema expects another field (it reads back as that field), so the TPT
# value itself is kept as custom attribute too.
STAND_IN = Transform(
    "stand_in", lambda v, _c: (v, False), lambda _v, _c: None, "stands in for a missing mandatory value"
)


def _scale(factor: Decimal, name: str, note: str) -> Transform:
    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        try:
            return format_decimal(parse_decimal(v) * factor), True
        except ValueError:
            return v, True  # leave it to the schema check, which reports it

    def from_xml(v: str, _ctx: dict[str, str]) -> str | None:
        try:
            return format_decimal(parse_decimal(v) / factor)
        except ValueError:
            return v

    return Transform(name, to_xml, from_xml, note)


PCT100 = _scale(Decimal(100), "pct100", "TPT decimal fraction (0.035) ↔ FundsXML percent (3.5)")
BPS = _scale(Decimal(10000), "bps", "TPT decimal fraction (0.005) ↔ basis points (50)")


def _mapping(name: str, table: dict[str, str], note: str = "") -> Transform:
    reverse = {v: k for k, v in table.items()}

    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        key = v.strip()
        if key in table:
            return table[key], True
        low = {k.lower(): val for k, val in table.items()}
        if key.lower() in low:
            return low[key.lower()], True
        return None, False

    def from_xml(v: str, _ctx: dict[str, str]) -> str | None:
        return reverse.get(v.strip())

    return Transform(name, to_xml, from_xml, note)


COUPON_FREQUENCY = _mapping(
    "coupon_frequency",
    {"1": "YEAR", "2": "SEMI", "4": "QURT", "12": "MNTH", "52": "WEEK"},
    "number of coupons per year ↔ FrequencyType",
)
OPTION_DIRECTION = _mapping("option_direction", {"I": "Issuer", "B": "Bearer", "O": "Both"})
REDEMPTION_TYPE = _mapping("redemption_type", {"Bullet": "Bullet", "Sinkable": "Sinkable"})


def _rate_type_from(v: str, _ctx: dict[str, str]) -> str | None:
    return {"fix": "Fixed", "zero": "Fixed", "float": "Floating"}.get(v.strip().lower())


_RATE_TYPE = _mapping("rate_type", {"Fixed": "fix", "Floating": "float"})


def _rate_type_to(v: str, ctx: dict[str, str]) -> tuple[str | None, bool]:
    value, lossless = _RATE_TYPE.to_xml(v, ctx)
    # TPT has no zero-coupon type: a fixed rate of 0 % is one (read back as Fixed).
    if value == "fix" and _is_zero(ctx.get("33", "")):
        return "zero", lossless
    return value, lossless


def _is_zero(v: str) -> bool:
    try:
        return parse_decimal(v) == 0
    except ValueError:
        return False


RATE_TYPE = Transform(
    "rate_type",
    _rate_type_to,
    _rate_type_from,
    "Fixed ↔ fix (zero with a 0 % coupon, read back as Fixed), Floating ↔ float",
)
# A zero coupon bond without InterestRate: its coupon rate is 0 (so Fixed is written back as zero).
ZERO_COUPON_RATE = Transform(
    "zero_coupon_rate",
    lambda _v, _c: (None, False),
    lambda v, _c: "0" if v.strip() == "zero" else None,
    "zero coupon → 0",
)


def _tpt_version_to(v: str, ctx: dict[str, str]) -> tuple[str | None, bool]:
    # The V7 block only accepts "V7.0"; the full label (or a V8 label) is kept separately.
    version = ctx.get("_version", "V7")
    return "V7.0", version == "V7" and v.strip() == VERSION_LABELS["V7"]


def _tpt_version_from(v: str, ctx: dict[str, str]) -> str | None:
    return VERSION_LABELS.get(ctx.get("_version", "V7"), VERSION_LABELS["V7"])


TPT_VERSION = Transform("tpt_version", _tpt_version_to, _tpt_version_from, "V7.0 in the TPT block")


def _securitised_to(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
    # V8 split code "e" into e1/e2/e3; the V7 block only knows "e".
    s = v.strip()
    if s.lower() in ("e1", "e2", "e3"):
        return "e", False
    return s, True


SECURITISED_V7 = Transform("securitised_v7", _securitised_to, _identity_from, "V8 e1/e2/e3 → e")


# -- CIC derived values ------------------------------------------------------


def cic_category(cic: str) -> str:
    """Third character of a CIC code: the asset category (1–9, 0, A–F)."""
    c = (cic or "").strip().upper()
    return c[2] if len(c) >= 3 else ""


def cic_subcategory(cic: str) -> str:
    c = (cic or "").strip().upper()
    return c[3] if len(c) >= 4 else ""


ASSET_TYPE_BY_CATEGORY = {
    "1": "BO",
    "2": "BO",
    "3": "EQ",
    "4": "SC",
    "5": "BO",
    "6": "BO",
    "7": "AC",
    "8": "LO",
    "9": "RE",
    "0": "CE",
    "A": "FU",
    "B": "OP",
    "C": "OP",
    "D": "SW",
    "E": "FU",
    "F": "SW",
}


def asset_type(cic: str) -> str | None:
    cat, sub = cic_category(cic), cic_subcategory(cic)
    if cat == "3" and sub == "4":
        return "PE"  # private equity
    if cat == "7" and sub in ("3", "4", "5"):
        return "FT"  # other deposits
    if cat == "E" and sub == "2":
        return "FX"  # FX forward
    if cat == "F" and sub == "2":
        return "OP"  # credit spread option
    return ASSET_TYPE_BY_CATEGORY.get(cat)


# Core position element per FundsXML AssetType.
POSITION_ELEMENT = {
    "BO": "Bond",
    "EQ": "Equity",
    "PE": "Equity",
    "SC": "ShareClass",
    "CE": "Certificate",
    "OP": "Option",
    "FU": "Future",
    "FX": "FXForward",
    "SW": "Swap",
    "AC": "Account",
    "FT": "FixedTimeDeposit",
    "LO": "Loan",
    "RE": "RealEstate",
}

FUTURE_TYPE = {"1": "EF", "2": "IRF", "3": "CF", "4": "OTHER", "5": "OTHER", "9": "OTHER"}
OPTION_TYPE = {"1": "EFO", "2": "IRO", "3": "CO", "4": "OTHER", "5": "OTHER", "6": "OTHER", "7": "OTHER"}
SWAP_TYPE = {
    "1": "Interestrateswap",
    "2": "Currencyswap",
    "3": "Crosscurrencyswap",
    "4": "Totalreturnswap",
    "5": "Assetswap",
    "7": "Commodityswap",
}


def _derived(name: str, fn: Callable[[str], str | None], note: str) -> Transform:
    def to_xml(v: str, _ctx: dict[str, str]) -> tuple[str | None, bool]:
        return fn(v), False

    def from_xml(_v: str, _ctx: dict[str, str]) -> str | None:
        return None

    return Transform(name, to_xml, from_xml, note)


def _future_type(cic: str) -> str | None:
    if cic_category(cic) == "E" and cic_subcategory(cic) == "1":
        return "FRA"
    return FUTURE_TYPE.get(cic_subcategory(cic), "OTHER")


def _option_type(cic: str) -> str | None:
    return OPTION_TYPE.get(cic_subcategory(cic), "OTHER")


def _swap_type(cic: str) -> str | None:
    if cic_category(cic) == "F":
        return "Creditdefaultswap" if cic_subcategory(cic) == "1" else "Totalreturnswap"
    return SWAP_TYPE.get(cic_subcategory(cic), "Interestrateswap")


def _call_put_to(cic: str, ctx: dict[str, str]) -> tuple[str | None, bool]:
    # A credit spread option (CIC xF2) is neither category B nor C: field 60 tells call from put.
    by_cic = {"B": "CALL", "C": "PUT"}.get(cic_category(cic))
    return by_cic or {"cal": "CALL", "put": "PUT"}.get(ctx.get("60", "").strip().lower()), False


def _convertible(cic: str) -> str | None:
    return "true" if cic_category(cic) == "2" and cic_subcategory(cic) == "2" else "false"


def _asset_type_from(v: str, _ctx: dict[str, str]) -> str | None:
    # Without a CIC classification only category and subcategory can be guessed: "XT" + both,
    # chosen so that asset_type() gives the same AssetType back.
    cic = {
        "BO": "29",
        "EQ": "39",
        "PE": "34",
        "SC": "49",
        "AC": "79",
        "FT": "73",
        "LO": "89",
        "RE": "99",
        "FU": "A9",
        "OP": "B9",
        "SW": "D9",
        "FX": "E2",
        "CE": "09",
        # FundsXML types without a TPT counterpart in this converter's CIC mapping
        "CP": "29",
        "RT": "39",
        "RI": "39",
        "CM": "79",
        "WA": "B9",
        "CO": "09",
        "FE": "09",
    }.get(v.strip())
    return f"XT{cic}" if cic else None


ASSET_TYPE = Transform(
    "cic_asset_type",
    lambda v, _c: (asset_type(v), False),
    _asset_type_from,
    "AssetType from the CIC category (3rd character)",
)
FUTURE_TYPE_T = _derived("cic_future_type", _future_type, "Future type from the CIC subcategory")
OPTION_TYPE_T = _derived("cic_option_type", _option_type, "Option type from the CIC subcategory")
SWAP_TYPE_T = _derived("cic_swap_type", _swap_type, "Swap type from the CIC subcategory")
CALL_PUT_T = Transform(
    "cic_call_put", _call_put_to, lambda _v, _c: None, "CIC category B = call, C = put, else field 60"
)
CONVERTIBLE_T = _derived("cic_convertible", _convertible, "CIC x22 = convertible bond")


def const(value: str) -> Transform:
    return Transform(
        f"const:{value}", lambda _v, _c: (value, False), lambda _v, _c: None, f"constant {value}"
    )
