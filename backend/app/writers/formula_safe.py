"""Values from an upload must never run as spreadsheet formulas in the files we write.

A FundsXML from a third party may carry an instrument name like ``=WEBSERVICE("https://…")``:

- openpyxl stores any string starting with ``=`` as a formula. Such cells are written as plain
  text instead, so the value itself is unchanged.
- In CSV, Excel evaluates a cell starting with ``=``, ``+``, ``-`` or ``@`` (or tab/CR). Such a text
  gets a leading ``'``, as OWASP recommends. Numbers like ``-1.5`` and a lone ``-`` stay as they are.
"""

from __future__ import annotations

from app.model.xmltree import parse_decimal

_CSV_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def xlsx_row(ws, values: list) -> list:
    """``values`` for ``ws.append`` (a write-only sheet), text starting with ``=`` kept as text."""
    from openpyxl.cell import WriteOnlyCell

    out = []
    for value in values:
        if isinstance(value, str) and value.startswith("="):
            cell = WriteOnlyCell(ws, value)
            cell.data_type = "s"
            value = cell
        out.append(value)
    return out


def csv_text(value: str) -> str:
    """``value`` for a CSV cell: a leading ``'`` when a spreadsheet would read it as a formula."""
    if len(value) < 2 or not value.startswith(_CSV_TRIGGERS):
        return value
    try:
        parse_decimal(value)
    except ValueError:
        return "'" + value
    return value


def pipe_text(value: str) -> str:
    """``value`` for an unquoted pipe file: no delimiter or line break inside, no formula."""
    return csv_text(value.replace("|", "/").replace("\n", " "))
