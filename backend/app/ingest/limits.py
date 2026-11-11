"""Guards for uploads that are small on the wire but huge once read.

A few KB can stand for millions of cells: a ZIP entry that unpacks a thousandfold, a sheet whose
last cell is XFD1048576, a CSV of nothing but line breaks. The readers check the archive before
opening it and read rows through a ``RowGuard``, so memory stays bounded by the position limit.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator

from openpyxl.utils.cell import column_index_from_string

from app.config import settings

MAX_ENTRIES = 200
MAX_UNZIPPED = 512 * 1024 * 1024
# Real XLSX/CSV entries compress about 5–15 : 1; zip bombs a thousandfold.
MAX_RATIO = 100
RATIO_FROM = 1024 * 1024  # small entries (styles, empty sheets) may compress better
MAX_SHARED_STRINGS = 64 * 1024 * 1024  # openpyxl keeps them in memory, even read-only
MAX_COLUMNS = 2048
# Rows a file may have beyond its positions: headers, notes, share class rows.
ROW_SLACK = 1000
# This many blank rows in a row end the table (a sheet sized to its last row, a padded export).
BLANK_RUN = 1000


class TooManyRowsError(ValueError):
    """The table has more rows than the service converts."""


def archive_problem(data: bytes) -> str | None:
    """Why ``data`` (a ZIP or XLSX) is too large once unpacked; None when it is fine or no ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile:
        return None  # the reader reports it
    if len(infos) > MAX_ENTRIES:
        return f"the archive has {len(infos)} entries (at most {MAX_ENTRIES})"
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > RATIO_FROM and info.file_size > MAX_RATIO * max(info.compress_size, 1):
            return f"{info.filename} unpacks to {info.file_size // (1024 * 1024)} MB from far less"
        if info.filename.lower().endswith("sharedstrings.xml") and info.file_size > MAX_SHARED_STRINGS:
            return f"{info.filename} unpacks to {info.file_size // (1024 * 1024)} MB"
    if total > MAX_UNZIPPED:
        mb = 1024 * 1024
        return f"the archive unpacks to {total // mb} MB (at most {MAX_UNZIPPED // mb} MB)"
    return None


def _too_many_rows() -> TooManyRowsError:
    return TooManyRowsError(f"the file has more than {settings.max_positions} positions")


class RowGuard:
    """Counts the rows of one table: stops at a long blank run, refuses more rows than allowed."""

    def __init__(self) -> None:
        self.cap = settings.max_positions + ROW_SLACK
        self.filled = 0
        self.blank_run = 0

    def take(self, row: list[str]) -> bool:
        """False once the table has ended; TooManyRowsError past the position limit."""
        if any(row):
            self.filled += 1
            self.blank_run = 0
            if self.filled > self.cap:
                raise _too_many_rows()
            return True
        self.blank_run += 1
        return self.blank_run <= BLANK_RUN


def guarded(rows: Iterable[list[str]], sniff: bool = False) -> list[list[str]]:
    """The rows up to the end of the table, without the blank rows after the last filled one.

    ``sniff``: only the first rows are read, to find a header; they are never too many.
    """
    guard = RowGuard()
    if sniff:
        guard.cap = float("inf")
    out: list[list[str]] = []
    for row in rows:
        if not guard.take(row):
            break
        out.append(row)
    while out and not any(out[-1]):
        out.pop()
    return out


def sheet_rows(ws, cell_text, max_row: int | None = None) -> Iterator[list[str]]:
    """The rows of a read-only worksheet as text, at most MAX_COLUMNS wide, trailing blanks cut."""
    width = min(ws.max_column or MAX_COLUMNS, MAX_COLUMNS)
    for raw in ws.iter_rows(max_row=max_row, max_col=width, values_only=True):
        n = len(raw)
        while n and raw[n - 1] in (None, ""):
            n -= 1
        yield [cell_text(c) for c in raw[:n]]


def text_lines(text: str) -> Iterator[str]:
    """The lines of ``text``, each with its "\n", without building them all at once."""
    return iter(io.StringIO(text, newline=None))


# ---------------------------------------------------------------------------
# XLSX row count before reading
# ---------------------------------------------------------------------------

_P = rb"(?:[A-Za-z_][\w.-]*:)?"  # optional namespace prefix
_SHEET_DATA = re.compile(rb"<" + _P + rb"sheetData\b")
_DIMENSION = re.compile(rb"<" + _P + rb"dimension\b[^>]*?\sref=[\"']([^\"']*)[\"']")
_ROW = re.compile(rb"<" + _P + rb"row\b([^>]*?)(/?)>")
_ROW_END = re.compile(rb"</" + _P + rb"row\s*>")
_SHEET_DATA_END = re.compile(rb"</" + _P + rb"sheetData\s*>")
_CELL = re.compile(rb"<" + _P + rb"c\b([^>]*?)(?:/>|>(.*?)</" + _P + rb"c\s*>)", re.DOTALL)
_ROW_NUMBER = re.compile(rb"(?:^|\s)r=[\"'](\d+)[\"']")
_CELL_REF = re.compile(rb"(?:^|\s)r=[\"']([A-Z]{1,3})\d+[\"']")
_CELL_TYPE = re.compile(rb"(?:^|\s)t=[\"'](\w+)[\"']")
_VALUE = re.compile(rb"<" + _P + rb"v>([^<]*)</" + _P + rb"v\s*>")
_TEXT = re.compile(rb"<" + _P + rb"t(?:\s[^>]*)?>([^<]+)</")
_NUMBER = re.compile(rb"\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\s*")
_CHUNK = 1024 * 1024


def check_xlsx_rows(data: bytes, pick: Callable[[list[str]], Iterable[int]]) -> None:
    """TooManyRowsError if a worksheet the reader would read certainly has too many rows.

    Reading a large sheet with openpyxl takes many seconds before ``RowGuard`` refuses it;
    this scans the sheet XML for rows with a value that is certainly not empty (a number, a
    boolean, an inline or formula string) and applies the guard's rules to them: the
    sheet's dimension, the column limit, blank runs. Values in the shared string table count
    as maybe empty, so the count is a lower bound and the error is the one ``guarded`` would
    raise as well, only sooner. Nothing happens when the file is fine, unusual (the reader
    decides then) or no XLSX.

    ``pick`` chooses from the worksheet titles (in order) the ones the reader reads.
    """
    if _over_limit(data, pick):
        raise _too_many_rows()


def _over_limit(data: bytes, pick: Callable[[list[str]], Iterable[int]]) -> bool:
    from openpyxl.reader.excel import ExcelReader

    if data[:4] != b"PK\x03\x04" or archive_problem(data):
        return False
    try:
        reader = ExcelReader(io.BytesIO(data), read_only=True, data_only=True)
        reader.read_manifest()
        reader.read_workbook()
        sheets = [
            (sheet.name, rel.target)
            for sheet, rel in reader.parser.find_sheets()
            if rel.target in reader.valid_files and "chartsheet" not in rel.Type
        ]
        targets = [sheets[i][1] for i in pick([name for name, _ in sheets])]
        return any(_sheet_over_limit(reader.archive, target) for target in targets)
    except Exception:  # noqa: BLE001 – not decidable here; the reader reports what is wrong
        return False


def _sheet_over_limit(archive: zipfile.ZipFile, target: str) -> bool:
    from openpyxl.utils.cell import range_boundaries

    cap = settings.max_positions + ROW_SLACK
    with archive.open(target) as src:
        buf, pos, eof = b"", 0, False

        def more() -> bool:
            nonlocal buf, pos, eof
            chunk = src.read(_CHUNK)
            eof = not chunk
            buf, pos = buf[pos:] + chunk, 0
            return not eof

        while not (m := _SHEET_DATA.search(buf)):
            if not more():
                return False
        head = buf[: m.start()]
        max_row, width = None, MAX_COLUMNS
        if dim := _DIMENSION.search(head):
            _min_col, _min_row, max_col, max_row = range_boundaries(dim.group(1).decode("ascii"))
            width = min(max_col or MAX_COLUMNS, MAX_COLUMNS)
        if max_row is not None and max_row <= cap:
            return False  # openpyxl reads no rows beyond the dimension
        pos = m.end()
        counter, filled, blank_run = 1, 0, 0
        while True:
            row = _ROW.search(buf, pos)
            end = row and (row.end() if row.group(2) else _ROW_END.search(buf, row.end()))
            if row is None or end is None:
                if _SHEET_DATA_END.search(buf, pos) or not more():
                    return False
                continue
            number = _ROW_NUMBER.search(row.group(1))
            if number is None:
                return False  # rows without numbers: leave it to the reader
            idx = int(number.group(1))
            if max_row is not None and idx > max_row:
                return False
            if idx < counter:
                return False
            blank_run += idx - counter  # rows left out are blank rows
            if blank_run > BLANK_RUN:
                return False
            counter = idx + 1
            body = b"" if row.group(2) else buf[row.end() : end.start()]
            pos = row.end() if row.group(2) else end.end()
            if b"<!" in body:
                return False  # comments or CDATA: leave it to the reader
            if _has_value(body, width):
                filled += 1
                blank_run = 0
                if filled > cap:
                    return True
            else:
                blank_run += 1
            if blank_run > BLANK_RUN:
                return False


def _has_value(row: bytes, width: int) -> bool:
    """Whether a cell of the row within ``width`` columns certainly has a non-empty value."""
    for cell in _CELL.finditer(row):
        attrs, content = cell.group(1), cell.group(2)
        if not content:
            continue
        ref = _CELL_REF.search(attrs)
        if ref is None or column_index_from_string(ref.group(1).decode("ascii")) > width:
            continue
        kind = _CELL_TYPE.search(attrs)
        kind = kind.group(1) if kind else b"n"
        if kind == b"inlineStr":
            if b"rPh" not in content and any(t.strip() for t in _TEXT.findall(content)):
                return True
            continue
        value = _VALUE.search(content)
        if value is None:
            continue
        v = value.group(1)
        if (
            (kind == b"n" and _NUMBER.fullmatch(v))
            or (kind == b"b" and v in (b"0", b"1"))
            or (kind in (b"e", b"str") and v.strip())
        ):
            return True
    return False
