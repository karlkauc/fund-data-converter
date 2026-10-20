"""TPT field catalogs (V7, V8) synced from findatex-validator (tools/sync_specs.py)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parent
VERSIONS = ("V7", "V8")
VERSION_LABELS = {
    "V7": "V7.0 (official) dated 25 November 2024",
    "V8": "V8.0 (official) dated 26 May 2026",
}


@dataclass(frozen=True)
class TptField:
    num_key: str  # "12", "8b", "105a", "1000"
    num_data: str  # "12_CIC_code_of_the_instrument"
    definition: str
    fundxml_hint: str  # column B of the spec ("Position / InstrumentCIC")
    kind: str  # NUMERIC, DATE, CLOSED_LIST, ...
    codes: tuple[str, ...]
    sii_flag: str  # M, C, O, I, NA, UNKNOWN

    @property
    def portfolio_level(self) -> bool:
        return self.fundxml_hint.strip().startswith("Portfolio") or self.num_key == "1000"

    @property
    def mandatory(self) -> bool:
        return self.sii_flag == "M"


class Catalog:
    def __init__(self, version: str, fields: list[TptField]):
        self.version = version
        self.fields = fields
        self.by_key = {f.num_key: f for f in fields}
        self._lookup = self._build_lookup()

    def _build_lookup(self) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for f in self.fields:
            for alias in (f.num_key, f.num_data, f.num_data.split("_", 1)[-1]):
                lookup.setdefault(_norm(alias), f.num_key)
        return lookup

    def match_header(self, header: str) -> str | None:
        """Map a column header to a numKey (``12``, ``8b``) or None.

        Accepts the bare number, ``12_anything``, the full NUM_DATA name and
        the name without its number, compared case- and punctuation-insensitively.
        """
        h = (header or "").strip()
        if not h:
            return None
        m = re.match(r"^\s*(\d{1,4}[a-z]?)(?:[\s_.:\-)]|$)", h, re.IGNORECASE)
        if m and m.group(1).lower() in self.by_key:
            return m.group(1).lower()
        return self._lookup.get(_norm(h))

    def key_order(self) -> list[str]:
        return [f.num_key for f in self.fields]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


@lru_cache(maxsize=4)
def load_catalog(version: str) -> Catalog:
    if version not in VERSIONS:
        raise ValueError(f"unsupported TPT version {version}")
    data = json.loads((SPEC_DIR / f"tpt_{version.lower()}.json").read_text(encoding="utf-8"))
    fields = []
    for f in data["fields"]:
        cod = f.get("codification") or {}
        fields.append(
            TptField(
                num_key=f["numKey"].lower(),
                num_data=f["numData"],
                definition=(f.get("definition") or "").strip(),
                fundxml_hint=(f.get("fundXmlPath") or "").strip(),
                kind=cod.get("kind") or "UNKNOWN",
                codes=tuple(c["code"] for c in cod.get("closedList", [])),
                sii_flag=(f.get("flags") or {}).get("SOLVENCY_II", "UNKNOWN"),
            )
        )
    return Catalog(version, fields)
