"""TPT ⇄ openfunds through FundsXML: what the intermediate document cannot pass on.

TPT → openfunds keeps every TPT field: fields without an openfunds column travel as non-openfunds
columns ``TPT_<field>`` (``non_openfunds_columns``). openfunds → TPT can only pass on what TPT has a
field for: the share class key, name, currency, NAV, price and the holdings; everything else of
the openfunds file is reported as not carried.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.mapping.openfunds_holdings import (
    INSTRUMENT_IDS,
    OTHER_ID,
    OTHER_ID_TYPE,
    UNDERLYING_IDS,
    field_pairs,
    tpt_keys,
)
from app.mapping.openfunds_rules import OF_FUND, STATIC_RULES
from app.mapping.rules import rules_for

# TPT portfolio contexts and where their paths start, relative to the share class ("SC") or fund ("F").
_TPT_CONTEXTS = {
    "shareclass": "SC:",
    "sc_nav": "SC:TotalAssetValues/TotalAssetValue/",
    "sc_price": "SC:Prices/Price/",
    "fund_info": "F:",
}
_KEYS = {"OFST020000", "OFST020001", "OFST020002"}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path)


def _of_path(rule) -> str:
    return _norm(("F:" if rule.ctx == OF_FUND else "SC:") + rule.path)


@lru_cache(maxsize=1)
def tpt_carried_columns() -> frozenset[str]:
    """openfunds share class columns whose FundsXML element a TPT field is read from."""
    tpt_paths = {_norm(prefix + r.path) for ctx, prefix in _TPT_CONTEXTS.items() for r in rules_for(ctx)}
    carried = {r.field for r in STATIC_RULES if _of_path(r) in tpt_paths}
    return frozenset(carried | _KEYS)


@lru_cache(maxsize=1)
def openfunds_carried_fields() -> frozenset[str]:
    """TPT portfolio fields whose FundsXML element an openfunds column is read from."""
    of_paths = {_of_path(r) for r in STATIC_RULES}
    return frozenset(
        r.field
        for ctx, prefix in _TPT_CONTEXTS.items()
        for r in rules_for(ctx)
        if _norm(prefix + r.path) in of_paths
    )


def not_carried_to_tpt(
    shareclasses: list[dict[str, str]], holdings: list[dict[str, str]], extra
) -> list[str]:
    """Columns of an openfunds file that a TPT file has no field for."""
    carried = tpt_carried_columns()
    holding_cols = {p.of_id for p in field_pairs()} | {c for c, _ in INSTRUMENT_IDS + UNDERLYING_IDS}
    holding_cols |= {OTHER_ID, OTHER_ID_TYPE}
    lost: dict[str, None] = {}
    for rec in shareclasses:
        for col in rec:
            if col not in carried:
                lost[col] = None
    for rec in holdings:
        for col in rec:
            if col not in holding_cols and col not in _KEYS:
                lost[col] = None
    for header in extra:
        if not header.startswith("TPT_"):
            lost[header] = None
    return list(lost)


def tpt_fields_without_column(rows: list[dict[str, str]]) -> list[str]:
    """TPT fields of a TPT file that openfunds has no column for (lost without ``TPT_`` columns)."""
    known = tpt_keys() | openfunds_carried_fields() | {"1", "2"}
    out: dict[str, None] = {}
    for row in rows:
        for key, value in row.items():
            if value and key not in known:
                out[key] = None
    return list(out)
