"""TPT values that FundsXML does not carry as such but implies.

Applied to rows read from the core structures only (a TPT block is taken as
it is). Every rule here fills an empty field and never overrides a value:

* clean values (23/25): market value minus accrued interest; instruments
  without accrued interest (equities, funds, derivatives, cash without an
  interest amount) have clean = market value;
* accrued interest in quotation currency (125) from the portfolio currency
  amount (126);
* market exposure (27/28/30): for derivatives the commitment value of
  ``Position/Exposures``, for other instruments the market value – the TPT
  definition only distinguishes the two for derivatives;
* underlying asset category (131) from the CIC (S.06.03 categories);
* code types 48/51/116/120 = 9 ("none") when no LEI is given;
* complete SCR delivery (11) = N when no SCR contribution (97–105b) is given.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.mapping.transforms import cic_category
from app.model.xmltree import format_decimal, parse_decimal

# Fields this module (or a read-only rule) may fill although the source leaves them empty.
DERIVED_FIELDS = frozenset(
    {"7", "11", "116", "120", "12", "14", "15", "18", "19", "22", "23", "25", "27", "28", "30", "32", "34"}
    | {"35", "39", "46", "47", "48", "51", "52", "125", "126", "131", "148"}
)

SCR_FIELDS = ("97", "98", "99", "100", "101", "102", "103", "104", "105", "105a", "105b")
DERIVATIVE_CATEGORIES = frozenset("ABCDEF")
# CIC categories whose market value may contain accrued interest.
INTEREST_BEARING = frozenset("12568")

_CENT = Decimal("0.01")
_WEIGHT = Decimal("1E-12")


def dec(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return parse_decimal(value)
    except (ValueError, InvalidOperation):
        return None


def amount(d: Decimal) -> str:
    return format_decimal(d.quantize(_CENT, ROUND_HALF_UP))


def complete_position(values: dict[str, str], exposure_pc: Decimal | None, pc_per_qc: Decimal | None) -> None:
    """``exposure_pc``: commitment value in portfolio currency; ``pc_per_qc``: QC → PC rate."""
    category = cic_category(values.get("12", ""))
    same_ccy = values.get("21") and values.get("21") == values.get("4")

    def to_qc(key_pc: str, key_qc: str) -> None:
        if values.get(key_qc) or not values.get(key_pc):
            return
        if same_ccy:
            values[key_qc] = values[key_pc]
        elif pc_per_qc and (pc := dec(values[key_pc])) is not None:
            values[key_qc] = amount(pc / pc_per_qc)

    def to_pc(key_qc: str, key_pc: str) -> None:
        if values.get(key_pc) or not values.get(key_qc):
            return
        if same_ccy:
            values[key_pc] = values[key_qc]
        elif pc_per_qc and (qc := dec(values[key_qc])) is not None:
            values[key_pc] = amount(qc * pc_per_qc)

    to_pc("23", "25")
    to_pc("125", "126")

    mv, accrued = dec(values.get("24")), dec(values.get("126"))
    if not values.get("25") and mv is not None:
        if accrued is not None:
            values["25"] = amount(mv - accrued)
        elif category and category not in INTEREST_BEARING:
            values["25"] = values["24"]
    to_qc("25", "23")
    to_qc("126", "125")

    if category in DERIVATIVE_CATEGORIES:
        if not values.get("28") and exposure_pc is not None:
            values["28"] = amount(exposure_pc)
        to_qc("28", "27")
    elif category:
        values.setdefault("27", values.get("22", ""))
        values.setdefault("28", values.get("24", ""))
        values.setdefault("30", values.get("26", ""))

    if category and not values.get("131"):
        values["131"] = underlying_asset_category(values["12"])
    if not values.get("47") and not values.get("48"):
        values["48"] = "9"
    if not values.get("50") and not values.get("51"):
        values["51"] = "9"


def complete_portfolio(rows: list[dict[str, str]]) -> None:
    """Portfolio-level defaults and the exposure weight of derivatives (exposure / net assets)."""
    if not rows:
        return
    total = sum((d for r in rows if (d := dec(r.get("24"))) is not None), Decimal(0))
    no_scr = not any(r.get(k) for r in rows for k in SCR_FIELDS)
    for r in rows:
        if no_scr and not r.get("11"):
            r["11"] = "N"
        if not r.get("115") and not r.get("116"):
            r["116"] = "9"
        if not r.get("119") and not r.get("120"):
            r["120"] = "9"
        if not r.get("30") and total and (exposure := dec(r.get("28"))) is not None:
            r["30"] = format_decimal((exposure / total).quantize(_WEIGHT, ROUND_HALF_UP))


def underlying_asset_category(cic: str) -> str:
    """S.06.03 category: the CIC category; equities split into listed (3L) and not listed (3X)."""
    category = cic_category(cic)
    if category == "3":
        return "3X" if cic.strip().upper()[:2] in ("XL", "XT") else "3L"
    return category
