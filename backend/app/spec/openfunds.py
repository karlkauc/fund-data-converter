"""openfunds field catalog, parsed from the official field list PDF (tools/sync_openfunds.py)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from app.spec.catalog import SPEC_DIR, _norm

# OF-ID in a header cell: "OFST020000", "OFST001000(zh-Hant)", "OFST6010AT", "OFST020000 ISIN".
_HEADER = re.compile(r"^\s*(OF[A-Z]{2})(\d{4})(\d{2}|[A-Z]{2})(?:\(([A-Za-z0-9-]+)\))?(?=[\s_:.\-)]|$)")


@dataclass(frozen=True)
class FindatexRef:
    template: str  # TPT, EMT, EPT, EET, EFT, DCPT
    num: str  # "26", "00001", "100010"
    name: str  # "26_Valuation_weight"


@dataclass(frozen=True)
class OfField:
    of_id: str  # "OFST020000", "OFST6010XX"
    name: str
    tags: tuple[str, ...]
    level: str  # Company, Umbrella, Fund, Share Class, Listing, Holding, Others, ...
    data_type: str  # string, double, boolean, date, integer, time
    link: str
    introduced: str
    revoked: str
    description: str
    values: str
    codes: tuple[str, ...]
    example: str
    findatex: tuple[FindatexRef, ...]
    country_pattern: bool

    @property
    def prefix(self) -> str:
        return self.of_id[:4]

    @property
    def active(self) -> bool:
        return not self.revoked

    def ref(self, template: str) -> FindatexRef | None:
        return next((r for r in self.findatex if r.template == template), None)


@dataclass(frozen=True)
class HeaderMatch:
    of_id: str  # catalog OF-ID ("OFST6010XX" for a country column)
    column: str  # OF-ID as used in the file ("OFST6010AT", "OFST001000(zh-Hant)")
    country: str = ""
    language: str = ""


class OfCatalog:
    def __init__(self, version: str, date: str, fields: list[OfField]):
        self.version = version
        self.date = date
        self.fields = fields
        self.by_id = {f.of_id: f for f in fields}
        names: dict[str, list[str]] = {}
        for f in fields:
            names.setdefault(_norm(f.name), []).append(f.of_id)
        self._by_name = {k: v[0] for k, v in names.items() if len(v) == 1}

    def match_header(self, header: str) -> HeaderMatch | None:
        """Map a column header to an OF-ID, or None if it is not an openfunds column.

        Accepts the bare OF-ID with an optional language tag or trailing field name and the
        country variant of a multiple-country field (``OFST6010AT`` for ``OFST6010XX``).
        Unknown OF-IDs are returned too, so the reader can report them.
        """
        h = (header or "").strip()
        m = _HEADER.match(h)
        if not m:
            return None
        prefix, num, tail, lang = m.groups()
        of_id = f"{prefix}{num}{tail}"
        if tail.isalpha():
            pattern = f"{prefix}{num}XX"
            return (
                HeaderMatch(pattern, of_id, country=tail)
                if pattern in self.by_id
                else HeaderMatch(of_id, of_id)
            )
        column = f"{of_id}({lang})" if lang else of_id
        return HeaderMatch(of_id, column, language=lang or "")

    def match_name(self, header: str) -> str | None:
        """OF-ID for an unambiguous field name ("Share Class Currency"), for name-only headers."""
        return self._by_name.get(_norm(header or ""))

    def id_order(self) -> list[str]:
        return [f.of_id for f in self.fields]


@lru_cache(maxsize=1)
def load_openfunds() -> OfCatalog:
    data = json.loads((SPEC_DIR / "openfunds.json").read_text(encoding="utf-8"))
    fields = [
        OfField(
            of_id=f["id"],
            name=f["name"],
            tags=tuple(f["tags"]),
            level=f["level"],
            data_type=f["type"],
            link=f["link"],
            introduced=f["introduced"],
            revoked=f["revoked"],
            description=f["description"],
            values=f["values"],
            codes=tuple(f["codes"]),
            example=f["example"],
            findatex=tuple(FindatexRef(**r) for r in f["findatex"]),
            country_pattern=f["country_pattern"],
        )
        for f in data["fields"]
    ]
    return OfCatalog(data["version"], data["date"], fields)
