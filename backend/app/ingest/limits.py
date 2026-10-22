"""Guards for uploads that are small on the wire but huge once read.

A few KB can stand for millions of cells: a ZIP entry that unpacks a thousandfold, a sheet whose
last cell is XFD1048576, a CSV of nothing but line breaks. The readers check the archive before
opening it and read rows through a ``RowGuard``, so memory stays bounded by the position limit.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Iterator

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
                raise TooManyRowsError(f"the file has more than {settings.max_positions} positions")
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
