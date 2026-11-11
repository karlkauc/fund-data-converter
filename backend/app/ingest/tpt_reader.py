"""Read TPT files (XLSX or delimited text) into a version-tagged row model.

Header and delimiter detection follow findatex-validator's CsvLoader /
XlsxLoader: the header is the first of the first 50 rows with at least three
cells that match known TPT fields; delimiters ``|``, ``;``, tab and ``,`` are
scored on those lines and a ``sep=`` hint line is honoured.
"""

from __future__ import annotations

import csv
import io
import itertools
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.ingest.limits import archive_problem, check_xlsx_rows, guarded, sheet_rows, text_lines
from app.model.issues import Issue
from app.spec.catalog import VERSIONS, Catalog, load_catalog

HEADER_SCAN_ROWS = 50
MIN_HEADER_MATCHES = 3
DELIMITERS = ("|", ";", "\t", ",")


class TptReadError(ValueError):
    pass


@dataclass
class TptRow:
    values: dict[str, str]  # numKey -> raw string (non-empty values only)
    source_row: int  # 1-based row number in the file

    def get(self, key: str) -> str:
        return self.values.get(key, "")


@dataclass
class TptDocument:
    version: str
    version_source: str  # "field 1000", "fields 150/151", "default", "user"
    columns: list[tuple[int, str]]  # (column index, numKey)
    unmapped_headers: list[str]
    rows: list[TptRow]
    file_format: str  # "xlsx" or "csv"
    delimiter: str | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        return [k for _, k in self.columns]


def read_tpt(data: bytes, filename: str, version: str | None = None) -> TptDocument:
    """Parse ``data``; ``version`` forces V7/V8, otherwise it is detected."""
    if _looks_like_xlsx(data, filename):
        table = _read_xlsx(data)
        fmt, delim = "xlsx", None
    else:
        text = _decode(data)
        delim, table = _read_delimited(text)
        fmt = "csv"
    # Header matching uses the V8 catalog: it is a superset of V7 (148 only renamed).
    union = load_catalog("V8")
    header_idx = _find_header(table, union)
    if header_idx is None:
        raise TptReadError(
            "no TPT header row found: none of the first 50 rows contains at least three "
            "known TPT field names (e.g. 1_Portfolio_identifying_data or 12_CIC_code_of_the_instrument)"
        )
    header = table[header_idx]
    columns: list[tuple[int, str]] = []
    unmapped: list[str] = []
    seen: set[str] = set()
    issues: list[Issue] = []
    for idx, cell in enumerate(header):
        key = union.match_header(cell) or load_catalog("V7").match_header(cell)
        if key is None:
            if cell.strip():
                unmapped.append(cell.strip())
            continue
        if key in seen:
            issues.append(
                Issue(
                    "warning",
                    "duplicate_column",
                    f"Column for field {key} appears twice; the first one is used.",
                    field=key,
                )
            )
            continue
        seen.add(key)
        columns.append((idx, key))

    rows: list[TptRow] = []
    for offset, raw in enumerate(table[header_idx + 1 :], start=header_idx + 2):
        values = {}
        for idx, key in columns:
            if idx < len(raw):
                v = raw[idx].strip()
                if v:
                    values[key] = v
        if values:
            rows.append(TptRow(values, offset))
    if not rows:
        raise TptReadError("the TPT file contains a header row but no data rows")

    if version:
        chosen, source = version.upper(), "user"
        if chosen not in VERSIONS:
            raise TptReadError(f"unsupported TPT version {version}")
    else:
        chosen, source = detect_version(rows, seen)
    if unmapped:
        issues.append(
            Issue(
                "info",
                "unmapped_columns",
                f"{len(unmapped)} column(s) are not TPT fields and were ignored: "
                + ", ".join(unmapped[:8])
                + ("…" if len(unmapped) > 8 else ""),
                params={
                    "n": len(unmapped),
                    "columns": ", ".join(unmapped[:8]) + ("…" if len(unmapped) > 8 else ""),
                },
            )
        )
    if chosen == "V7" and seen & {"150", "151"}:
        issues.append(
            Issue(
                "warning",
                "v8_fields_in_v7",
                "Fields 150/151 only exist in TPT V8; they are kept but the file is treated as V7.",
            )
        )
    if chosen == "V8":
        issues += _not_applicable_filled(rows, load_catalog("V8"))
    return TptDocument(chosen, source, columns, unmapped, rows, fmt, delim, issues)


def _not_applicable_filled(rows: list[TptRow], catalog) -> list[Issue]:
    """V8 keeps 18 fields FinDatEx no longer maintains (17b, 29, 31, …, 141); they must be empty."""
    filled: dict[str, int] = {}
    for row in rows:
        for key in catalog.not_applicable_keys() & row.values.keys():
            filled[key] = filled.get(key, 0) + 1
    if not filled:
        return []
    keys = [k for k in catalog.key_order() if k in filled]
    names = ", ".join(catalog.by_key[k].num_data for k in keys)
    n = sum(filled.values())
    return [
        Issue(
            "warning",
            "v8_not_applicable",
            f"{n} value(s) in field(s) TPT V8 no longer maintains (must be empty): {names}. "
            "They are kept in FundsXML but left out of a V8 output.",
            field=",".join(keys),
            params={"n": n, "fields": names},
        )
    ]


def detect_version(rows: list[TptRow], keys: set[str]) -> tuple[str, str]:
    for row in rows[:20]:
        v = row.get("1000").upper()
        m = re.search(r"V\s*([78])(?:\.\d+)?\b", v) or re.match(r"\s*([78])\.\d+\b", v)
        if m:
            return f"V{m.group(1)}", "field 1000"
    if keys & {"150", "151"}:
        return "V8", "fields 150/151"
    return "V7", "default"


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _looks_like_xlsx(data: bytes, filename: str) -> bool:
    return data[:4] == b"PK\x03\x04" or filename.lower().endswith((".xlsx", ".xlsm"))


def _read_xlsx(data: bytes) -> list[list[str]]:
    from openpyxl import load_workbook

    if problem := archive_problem(data):
        raise TptReadError(f"not a readable XLSX file: {problem}")
    check_xlsx_rows(data, pick_sheet)  # before openpyxl spends seconds on a sheet it would refuse
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise TptReadError(f"not a readable XLSX file: {exc}") from exc
    try:
        return guarded(sheet_rows(_pick_sheet(wb), _cell_text))
    finally:
        wb.close()


def _pick_sheet(wb):
    return wb.worksheets[pick_sheet([ws.title for ws in wb.worksheets])[0]]


def pick_sheet(titles: list[str]) -> list[int]:
    """The sheet read (as a one-item list of its index): the first one, unless another one is
    plainly the TPT sheet."""
    for i, title in enumerate(titles):
        if re.search(r"\bTPT\b", title, re.IGNORECASE):
            return [i]
    return [0]


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        d = Decimal(repr(value))
        if d == d.to_integral_value():
            return str(d.quantize(Decimal(1)))
        s = format(d, "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    return str(value)


# ---------------------------------------------------------------------------
# Delimited text
# ---------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _read_delimited(text: str, limit: int | None = None) -> tuple[str, list[list[str]]]:
    """Delimiter and rows of a CSV; ``limit`` reads only that many rows."""
    lines = text_lines(text)
    head = list(itertools.islice(lines, HEADER_SCAN_ROWS + 1))
    hint = None
    first = head[0].rstrip("\r\n") if head else ""
    if first.lower().startswith("sep=") and len(first) >= 5:
        hint = first[4]
        head = head[1:]
    delim = hint or _detect_delimiter([line.rstrip("\r\n") for line in head[:HEADER_SCAN_ROWS]])
    body = itertools.islice(itertools.chain(head, lines), limit)
    if delim == "|":
        # Pipe files do not quote; quotes are literal text.
        rows = (line.rstrip("\r\n").split("|") for line in body)
    else:
        rows = csv.reader(body, delimiter=delim)
    return delim, guarded(rows, limit is not None)


def _detect_delimiter(lines: list[str]) -> str:
    union = load_catalog("V8")
    best, best_score = ";", -1
    for delim in DELIMITERS:
        score = 0
        for line in lines:
            cells = line.split(delim)
            if len(cells) < 2:
                continue
            matches = sum(1 for c in cells if union.match_header(c.strip().strip('"')))
            score = max(score, matches * 1000 + len(cells))
        if score > best_score:
            best, best_score = delim, score
    return best


def _find_header(table: list[list[str]], catalog: Catalog) -> int | None:
    for idx, row in enumerate(table[:HEADER_SCAN_ROWS]):
        matches = sum(1 for c in row if c and catalog.match_header(c))
        if matches >= MIN_HEADER_MATCHES:
            return idx
    return None
