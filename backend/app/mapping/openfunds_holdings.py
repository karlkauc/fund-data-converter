"""openfunds portfolio holdings (OFPH) ↔ TPT position fields.

openfunds documents the TPT counterpart of most holding fields ("TPT: 26_Valuation_weight"), so a
holding row is translated into a TPT row and written with the TPT core rules (positions and asset
master data). Values differ in a few code lists (``Call`` ↔ ``Cal``, ``annually`` ↔ ``1``), and
the instrument identifier is one TPT field pair (14 code, 15 type) for several openfunds columns.

Every translation is checked by translating back: only columns that come back unchanged count as
represented; the others are kept by the caller (custom attribute or non-openfunds column).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.model.xmltree import parse_decimal
from app.spec.openfunds import load_openfunds

# Instrument identifiers: openfunds column -> TPT field 15 code (1 ISIN, 2 CUSIP, 3 SEDOL, 4 WKN,
# 5 Bloomberg ticker, 8 FIGI, 9 other code of a numbering agency, 99 internal), in order of preference.
INSTRUMENT_IDS = (
    ("OFPH000100", "1"),
    ("OFPH000145", "2"),
    ("OFPH000140", "3"),
    ("OFPH000110", "4"),
    ("OFPH000155", "5"),
    ("OFPH000170", "8"),
    ("OFPH000120", "9"),  # Valor
    ("OFPH000150", "9"),  # APIR
    ("OFPH000130", "9"),  # exchange ticker
)
OTHER_ID, OTHER_ID_TYPE = "OFPH000190", "OFPH000195"
ISSUER_LEI = "OFPH000710"  # TPT 47 with code type 48 = 1 (LEI)
UNDERLYING_IDS = (("OFPH000805", "1"), ("OFPH000810", "4"), ("OFPH000815", "9"))
# TPT code -> openfunds column when reading back (first listed column per code).
_ID_COLUMN = {
    "1": "OFPH000100",
    "2": "OFPH000145",
    "3": "OFPH000140",
    "4": "OFPH000110",
    "5": "OFPH000155",
    "8": "OFPH000170",
}
_UNDERLYING_COLUMN = {"1": "OFPH000805", "4": "OFPH000810"}
# Columns whose TPT reference is the identifier pair, or that are not identifiers at all (MIC).
_ID_COLUMNS = {c for c, _ in INSTRUMENT_IDS + UNDERLYING_IDS} | {
    OTHER_ID,
    OTHER_ID_TYPE,
    ISSUER_LEI,
    "OFPH000135",
}
# Columns openfunds gives no TPT reference although TPT has the field: column -> TPT numKey.
EXTRA_PAIRS = (("OFPH000712", "52"),)  # Holding Issuer Domicile = 52_Issuer_country
# TPT code fields without an element of their own: FundsXML expresses them by the element (ISIN, LEI)
# that holds the value of their partner field, so they are written whenever the partner is.
IMPLIED_BY = {"15": "14", "69": "68", "48": "47"}

_FREQUENCY = {
    "weekly": "52",
    "monthly": "12",
    "quarterly": "4",
    "biannually": "2",
    "annually": "1",
    "other": "0",
}
CODES: dict[str, dict[str, str]] = {
    "32": {
        "Fixed": "Fixed",
        "Floating": "Floating",
        "Variable": "Variable",
        "Inflation-linked": "Inflation_linked",
    },
    "38": _FREQUENCY,
    "76": _FREQUENCY,
    "40": {"bullet": "Bullet", "sinkable": "Sinkable", "defaulted": "defaulted"},
    "42": {"Call": "Cal", "Put": "Put", "Cap": "Cap", "Floor": "Flr"},
    "44": {"issuer": "I", "bearer": "B", "both": "O"},
    "58": {"yes": "Y", "no": "N"},
    "64": {"American": "AM", "European": "EU", "Asian": "AS", "Bermudian": "BE"},
}


@dataclass(frozen=True)
class _Field:
    of_id: str
    tpt: str  # TPT numKey


@lru_cache(maxsize=1)
def field_pairs() -> tuple[_Field, ...]:
    """OFPH columns with a plain 1:1 TPT counterpart (identifiers excluded), plus ``EXTRA_PAIRS``."""
    out = []
    for f in load_openfunds().fields:
        ref = f.ref("TPT")
        if f.prefix == "OFPH" and ref and f.active and f.of_id not in _ID_COLUMNS:
            out.append(_Field(f.of_id, ref.num.lower()))
    out += [_Field(of_id, tpt) for of_id, tpt in EXTRA_PAIRS]
    return tuple(out)


@lru_cache(maxsize=1)
def tpt_keys() -> frozenset[str]:
    """TPT fields a holding row can carry."""
    return frozenset({p.tpt for p in field_pairs()} | {"14", "15", "68", "69", "47", "48"})


def with_implied(reached: set[str]) -> set[str]:
    """``reached`` plus the code fields its identifiers imply."""
    return reached | {code for code, partner in IMPLIED_BY.items() if partner in reached}


def _to_tpt_code(tpt: str, value: str) -> str | None:
    table = CODES.get(tpt)
    if table is None:
        return value
    low = {k.lower(): v for k, v in table.items()}
    return low.get(value.strip().lower())


def _from_tpt_code(tpt: str, value: str) -> str | None:
    table = CODES.get(tpt)
    if table is None:
        return value
    rev = {v.lower(): k for k, v in table.items()}
    return rev.get(value.strip().lower())


def holding_to_tpt(values: dict[str, str]) -> tuple[dict[str, str], dict[str, set[str]]]:
    """TPT values of a holding row and, per represented openfunds column, the TPT fields it went to."""
    tpt, sources = _forward(values)
    back = tpt_to_holding(tpt)[0]
    represented = {c: keys for c, keys in sources.items() if _same(values.get(c, ""), back.get(c, ""))}
    return tpt, represented


def tpt_to_holding(tpt: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    """openfunds values of a TPT row and the TPT fields that came back unchanged."""
    out: dict[str, str] = {}
    for pair in field_pairs():
        v = tpt.get(pair.tpt, "")
        if v and (value := _from_tpt_code(pair.tpt, v)) is not None:
            out.setdefault(pair.of_id, value)
    code, ident = tpt.get("15", "").strip(), tpt.get("14", "")
    if ident:
        column = _ID_COLUMN.get(code)
        if column:
            out[column] = ident
        else:
            out[OTHER_ID] = ident
            if code == "99":
                out[OTHER_ID_TYPE] = "Internal"
    code, ident = tpt.get("69", "").strip(), tpt.get("68", "")
    if ident and code in _UNDERLYING_COLUMN:
        out[_UNDERLYING_COLUMN[code]] = ident
    if tpt.get("47") and tpt.get("48", "").strip() == "1":
        out[ISSUER_LEI] = tpt["47"]
    back, _ = _forward(out)
    kept = {k for k, v in tpt.items() if _same(v, back.get(k, ""))}
    return out, kept


def _forward(values: dict[str, str]) -> tuple[dict[str, str], dict[str, set[str]]]:
    tpt: dict[str, str] = {}
    sources: dict[str, set[str]] = {}
    for pair in field_pairs():
        v = values.get(pair.of_id, "")
        if v and pair.tpt not in tpt and (code := _to_tpt_code(pair.tpt, v)) is not None:
            tpt[pair.tpt] = code
            sources[pair.of_id] = {pair.tpt}
    primary = next(((c, code) for c, code in INSTRUMENT_IDS if values.get(c)), None)
    if primary:
        tpt["14"], tpt["15"] = values[primary[0]], primary[1]
        sources[primary[0]] = {"14", "15"}
    elif values.get(OTHER_ID):
        internal = values.get(OTHER_ID_TYPE, "").strip().lower() == "internal"
        tpt["14"], tpt["15"] = values[OTHER_ID], "99" if internal else "9"
        sources[OTHER_ID] = {"14", "15"}
        if values.get(OTHER_ID_TYPE):
            sources[OTHER_ID_TYPE] = {"15"}
    underlying = next(((c, code) for c, code in UNDERLYING_IDS if values.get(c)), None)
    if underlying:
        tpt["68"], tpt["69"] = values[underlying[0]], underlying[1]
        sources[underlying[0]] = {"68", "69"}
    if values.get(ISSUER_LEI):
        tpt["47"], tpt["48"] = values[ISSUER_LEI], "1"
        sources[ISSUER_LEI] = {"47", "48"}
    return tpt, sources


def _same(a: str, b: str) -> bool:
    a, b = a.strip(), b.strip()
    if a == b:
        return True
    if not a or not b:
        return False
    try:
        return parse_decimal(a) == parse_decimal(b)
    except ValueError:
        return a.lower() == b.lower()
