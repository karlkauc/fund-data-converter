"""Read openfunds files (XLSX, delimited text, or a ZIP of both) into share class and holding records.

openfunds columns are identified by OF-IDs (``OFST020000``); a header cell may add a language tag
(``OFST001000(zh-Hant)``), the field name (``OFST020000 ISIN``) or carry a country code in place
of ``XX`` (``OFST6010AT``). The header is the first of the first 50 rows with at least three
OF-IDs. Columns without an OF-ID are non-openfunds fields (``OFST999990``): they are kept under
their header name.

Layouts:
- flat: one row per share class (``OFST020000`` ISIN), every field a column;
- narrow by country: several rows per share class with ``OFST600000`` naming the country of the
  ``OFST6nnnXX`` columns;
- narrow dynamic data: ``OFDY100100`` (field), ``OFDY100110`` (currency), ``OFDY100111`` (value).
Rows of the same share class are merged. A table whose columns are mostly ``OFPH`` fields holds
portfolio holdings, one row per position.
"""

from __future__ import annotations

import csv
import io
import itertools
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import PurePath

from app.ingest.limits import archive_problem, check_xlsx_rows, guarded, sheet_rows, text_lines
from app.ingest.tpt_reader import _cell_text, _decode, _looks_like_xlsx
from app.model.issues import Issue
from app.spec.openfunds import OfCatalog, OfField, load_openfunds

HEADER_SCAN_ROWS = 50
SNIFF_BYTES = 256 * 1024  # enough for the header rows when only sniffing
MIN_HEADER_MATCHES = 3
DELIMITERS = ("|", ";", "\t", ",")
IGNORE = "[IGNORE]"
ISIN = "OFST020000"
INSTRUMENT_ID = "OFST020001"
COUNTRY = "OFST600000"
DYN_TYPE, DYN_CCY, DYN_VALUE = "OFDY100100", "OFDY100110", "OFDY100111"
PRICE_CCY = "OFDY000010"
_OF_CELL = re.compile(r"^\s*OF[A-Z]{2}\d{4}[0-9A-Z]{2}\b")


class OpenfundsReadError(ValueError):
    pass


@dataclass
class OfRecord:
    values: dict[str, str]  # column OF-ID ("OFST020000", "OFST6010AT", "OFST001000(zh-Hant)") -> raw value
    extra: dict[str, str]  # non-openfunds columns: header -> raw value
    source: str  # "sheet:row" or "file:row"

    def get(self, key: str) -> str:
        return self.values.get(key, "")


@dataclass
class OfDocument:
    shareclasses: list[OfRecord]
    holdings: list[OfRecord]
    columns: list[str]  # OF-ID columns in file order (share class and holding tables)
    extra_columns: list[str]
    layout: str  # "flat" | "narrow"
    file_format: str  # "xlsx" | "csv" | "zip"
    delimiter: str | None = None
    issues: list[Issue] = field(default_factory=list)


@dataclass
class _Table:
    name: str
    rows: list[list[str]]
    delimiter: str | None = None


def looks_like_openfunds(data: bytes, filename: str) -> bool:
    """Cheap sniff for the service: a header row with at least three OF-IDs."""
    try:
        tables, _, _ = _tables(data, filename, HEADER_SCAN_ROWS)
    except OpenfundsReadError:
        return False
    return any(_find_header(t.rows) is not None for t in tables)


def read_openfunds(data: bytes, filename: str) -> OfDocument:
    catalog = load_openfunds()
    tables, fmt, delim = _tables(data, filename)
    issues: list[Issue] = []
    shareclasses: dict[str, OfRecord] = {}
    holdings: list[OfRecord] = []
    columns: list[str] = []
    extra_columns: list[str] = []
    narrow = False
    found = False
    unknown: dict[str, None] = {}
    revoked: dict[str, None] = {}
    ignored = 0
    for table in tables:
        idx = _find_header(table.rows)
        if idx is None:
            continue
        found = True
        cols, extras = _header(table.rows[idx], catalog, issues, unknown, revoked)
        of_ids = [c for _, c in cols]
        is_holdings = sum(1 for c in of_ids if c.startswith("OFPH")) * 2 >= len(of_ids)
        narrow |= not is_holdings and (COUNTRY in of_ids or DYN_TYPE in of_ids)
        columns += [c for c in of_ids if c not in columns]
        extra_columns += [h for _, h in extras if h not in extra_columns]
        first = idx + 1
        if first < len(table.rows) and _is_name_row(table.rows[first], cols, catalog):
            first += 1
        for rownum, raw in enumerate(table.rows[first:], start=first + 1):
            values, extra = {}, {}
            for i, key in cols:
                v = raw[i].strip() if i < len(raw) else ""
                if v == IGNORE:
                    ignored += 1
                elif v:
                    values[key] = v
            for i, header in extras:
                v = raw[i].strip() if i < len(raw) else ""
                if v and v != IGNORE:
                    extra[header] = v
            if not values and not extra:
                continue
            rec = OfRecord(values, extra, f"{table.name}:{rownum}")
            if is_holdings:
                holdings.append(rec)
            else:
                _merge(shareclasses, _unpivot(rec, issues), issues)
    if not found:
        raise OpenfundsReadError(
            "no openfunds header row found: none of the first 50 rows contains at least three "
            "OF-IDs (e.g. OFST020000 for the ISIN)"
        )
    if not shareclasses and not holdings:
        raise OpenfundsReadError("the openfunds file contains a header row but no data rows")
    if unknown:
        issues.append(
            Issue(
                "warning",
                "of_unknown_field",
                f"{len(unknown)} OF-ID(s) are not in openfunds {catalog.version}; they are kept as is: "
                + _list(unknown),
                params={"n": len(unknown), "columns": _list(unknown), "version": catalog.version},
            )
        )
    if revoked:
        issues.append(
            Issue(
                "info",
                "of_revoked_field",
                f"{len(revoked)} field(s) are revoked in openfunds {catalog.version}: " + _list(revoked),
                params={"n": len(revoked), "columns": _list(revoked), "version": catalog.version},
            )
        )
    if extra_columns:
        issues.append(
            Issue(
                "info",
                "of_non_openfunds_column",
                f"{len(extra_columns)} column(s) are not openfunds fields; they are kept under their "
                "header name: " + _list(extra_columns),
                params={"n": len(extra_columns), "columns": _list(extra_columns)},
            )
        )
    if ignored:
        issues.append(
            Issue(
                "info",
                "of_ignore_value",
                f"{ignored} value(s) are [IGNORE] and were treated as not delivered.",
                params={"n": ignored},
            )
        )
    records = list(shareclasses.values())
    checks = _ValueChecks(catalog)
    for rec in records + holdings:
        issues += checks.issues(rec)
    return OfDocument(
        records, holdings, columns, extra_columns, "narrow" if narrow else "flat", fmt, delim, issues
    )


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _unpivot(rec: OfRecord, issues: list[Issue]) -> OfRecord:
    """Resolve the narrow layouts into flat columns."""
    values = dict(rec.values)
    country = values.pop(COUNTRY, "").upper()
    if country:
        for key in [k for k in values if k.endswith("XX") and k.startswith("OFST6")]:
            values[key[:-2] + country] = values.pop(key)
    dyn = values.pop(DYN_TYPE, "")
    if dyn:
        value = values.pop(DYN_VALUE, "")
        ccy = values.pop(DYN_CCY, "")
        if value:
            values[dyn.strip().upper()] = value
        if ccy:
            values.setdefault(PRICE_CCY, ccy)
    return OfRecord(values, rec.extra, rec.source)


def _merge(records: dict[str, OfRecord], rec: OfRecord, issues: list[Issue]) -> None:
    key = rec.get(ISIN) or rec.get(INSTRUMENT_ID) or f"#{rec.source}"
    have = records.get(key)
    if have is None:
        records[key] = rec
        return
    for target, incoming in ((have.values, rec.values), (have.extra, rec.extra)):
        for k, v in incoming.items():
            old = target.setdefault(k, v)
            if old != v:
                issues.append(
                    Issue(
                        "warning",
                        "of_value_conflict",
                        f"{key}: {k} is given twice ({old!r} and {v!r} in {rec.source}); "
                        "the first one is used.",
                        field=k,
                        value=v,
                        params={"key": key, "field": k, "first": old, "second": v},
                    )
                )


class _ValueChecks:
    """``_invalid`` for every value of a record; columns and repeated values are looked up once."""

    def __init__(self, catalog: OfCatalog):
        self.catalog = catalog
        self.fields: dict[str, OfField | None] = {}
        self.reasons: dict[tuple[str, str], str | None] = {}

    def field(self, col: str) -> OfField | None:
        if col not in self.fields:
            match = self.catalog.match_header(col)
            self.fields[col] = self.catalog.by_id.get(match.of_id) if match else None
        return self.fields[col]

    def reason(self, f: OfField, value: str) -> str | None:
        key = (f.of_id, value)
        if key not in self.reasons:
            self.reasons[key] = _invalid(f.data_type, f.codes, value, f.values)
        return self.reasons[key]

    def issues(self, rec: OfRecord) -> list[Issue]:
        issues = []
        for col, value in rec.values.items():
            f = self.field(col)
            if f is None:
                continue
            reason = self.reason(f, value)
            if not reason:
                continue
            issues.append(
                Issue(
                    "warning",
                    "of_value_invalid",
                    f"{rec.source}: {col} ({f.name}) = {value!r} is not {reason}.",
                    field=col,
                    value=value,
                    params={"field": col, "name": f.name, "value": value, "expected": reason},
                )
            )
        return issues


def _invalid(data_type: str, codes: tuple[str, ...], value: str, values: str = "") -> str | None:
    v = value.strip()
    if data_type in ("double", "integer"):
        try:
            d = Decimal(v.replace(",", "") if v.count(",") and v.count(".") else v.replace(",", "."))
        except InvalidOperation:
            return "a number"
        if data_type == "integer" and d != d.to_integral_value():
            return "an integer"
        return None
    if data_type == "boolean":
        return None if v.lower() in ("yes", "no", "true", "false", "y", "n", "1", "0") else '"yes" or "no"'
    if data_type == "date":
        if values.strip() == "MM-DD":  # e.g. the fiscal year end; a full date is accepted as well
            m = re.fullmatch(r"(?:--|\d{4}-)?(\d{2})-(\d{2})", v)
            try:
                return None if m and date(2000, int(m[1]), int(m[2])) else "a month and day (MM-DD)"
            except ValueError:
                return "a month and day (MM-DD)"
        try:
            date.fromisoformat(v[:10])
        except ValueError:
            return "a date (YYYY-MM-DD)"
        return None
    if codes and len(codes) > 1 and data_type == "string":
        lowered = {c.strip().lower() for c in codes}
        parts = [p.strip().lower() for p in v.split(";")] if ";" not in "".join(codes) else [v.lower()]
        if not all(p in lowered for p in parts):
            return "one of " + " / ".join(codes[:8]) + ("…" if len(codes) > 8 else "")
    return None


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _header(
    row: list[str], catalog: OfCatalog, issues: list[Issue], unknown: dict, revoked: dict
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    cols: list[tuple[int, str]] = []
    extras: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i, cell in enumerate(row):
        cell = cell.strip()
        match = catalog.match_header(cell)
        if match is None:
            if cell:
                extras.append((i, cell))
            continue
        if match.column in seen:
            issues.append(
                Issue(
                    "warning",
                    "duplicate_column",
                    f"Column {match.column} appears twice; the first one is used.",
                    field=match.column,
                )
            )
            continue
        seen.add(match.column)
        f = catalog.by_id.get(match.of_id)
        if f is None:
            unknown[match.column] = None
        elif f.revoked:
            revoked[match.of_id] = None
        cols.append((i, match.column))
    return cols, extras


def _is_name_row(row: list[str], cols: list[tuple[int, str]], catalog: OfCatalog) -> bool:
    """A second header row with the field names ("ISIN", "Share Class Currency", …)."""
    hits = 0
    for i, col in cols:
        match = catalog.match_header(col)
        f = catalog.by_id.get(match.of_id) if match else None
        if f and i < len(row) and row[i].strip().lower() == f.name.lower():
            hits += 1
    return hits * 2 >= max(1, len(cols))


def _find_header(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if sum(1 for c in row if c and _OF_CELL.match(c)) >= MIN_HEADER_MATCHES:
            return idx
    return None


def _list(items) -> str:
    items = list(items)
    return ", ".join(items[:8]) + ("…" if len(items) > 8 else "")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def _tables(data: bytes, filename: str, limit: int | None = None) -> tuple[list[_Table], str, str | None]:
    """The tables of the file; ``limit`` reads only that many rows of each (enough to find a header)."""
    if data[:4] == b"PK\x03\x04" and not _is_xlsx(data):
        return _zip_tables(data, limit)
    if _looks_like_xlsx(data, filename):
        return _xlsx_tables(data, limit), "xlsx", None
    text = _decode(data[:SNIFF_BYTES] if limit else data)
    delim, rows = _read_delimited(text, limit)
    return [_Table(PurePath(filename or "upload").name, rows, delim)], "csv", delim


def _is_xlsx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "[Content_Types].xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def _zip_tables(data: bytes, limit: int | None = None) -> tuple[list[_Table], str, str | None]:
    tables: list[_Table] = []
    delim = None
    if problem := archive_problem(data):
        raise OpenfundsReadError(f"not a readable ZIP file: {problem}")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise OpenfundsReadError(f"not a readable ZIP file: {exc}") from exc
    with zf:
        for info in zf.infolist():
            name = info.filename
            if info.is_dir() or name.startswith("__MACOSX/"):
                continue
            lower = name.lower()
            if lower.endswith((".xlsx", ".xlsm")):
                tables += _xlsx_tables(zf.read(info), limit)
            elif lower.endswith((".csv", ".txt", ".tsv")):
                with zf.open(info) as f:
                    text = _decode(f.read(SNIFF_BYTES) if limit else f.read())
                d, rows = _read_delimited(text, limit)
                delim = delim or d
                tables.append(_Table(PurePath(name).name, rows, d))
    if not tables:
        raise OpenfundsReadError("the ZIP file contains no XLSX or CSV file")
    return tables, "zip", delim


def _xlsx_tables(data: bytes, limit: int | None = None) -> list[_Table]:
    from openpyxl import load_workbook

    if problem := archive_problem(data):
        raise OpenfundsReadError(f"not a readable XLSX file: {problem}")
    if limit is None:
        check_xlsx_rows(data, lambda titles: range(len(titles)))  # every sheet is read
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise OpenfundsReadError(f"not a readable XLSX file: {exc}") from exc
    try:
        return [
            _Table(ws.title, guarded(sheet_rows(ws, _of_cell_text, limit), limit is not None))
            for ws in wb.worksheets
        ]
    finally:
        wb.close()


def _of_cell_text(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _cell_text(value)


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
        return delim, guarded((line.rstrip("\r\n").split("|") for line in body), limit is not None)
    return delim, guarded(csv.reader(body, delimiter=delim), limit is not None)


def _detect_delimiter(lines: list[str]) -> str:
    best, best_score = ";", -1
    for delim in DELIMITERS:
        score = 0
        for line in lines:
            cells = line.split(delim)
            if len(cells) < 2:
                continue
            matches = sum(1 for c in cells if _OF_CELL.match(c.strip().strip('"')))
            score = max(score, matches * 1000 + len(cells))
        if score > best_score:
            best, best_score = delim, score
    return best
