"""Write openfunds share class and holding records as XLSX or delimited text.

Columns follow the openfunds field order (country and language variants right after their
field); non-openfunds columns (``OFST999990``) come last under their own name. XLSX holds the
share classes in the sheet ``openfunds`` and the positions in ``Holdings``. Delimited text is one
file per table, zipped when there are holdings.
"""

from __future__ import annotations

import csv
import io
import zipfile

from app.model.xmltree import parse_decimal
from app.spec.openfunds import OfCatalog, load_openfunds

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_SHARECLASSES = "openfunds"
SHEET_HOLDINGS = "Holdings"


def columns(
    rows: list[dict[str, str]], catalog: OfCatalog, prefixes: tuple[str, ...] | None = None
) -> list[str]:
    """The columns of ``rows`` in openfunds order; ``prefixes`` adds every active field of those prefixes."""
    present = {k for r in rows for k in r}
    if prefixes:
        present |= {
            f.of_id for f in catalog.fields if f.prefix in prefixes and f.active and not f.country_pattern
        }
    order = {of_id: i for i, of_id in enumerate(catalog.id_order())}

    def key(col: str) -> tuple[int, int, str]:
        match = catalog.match_header(col)
        if match is None:
            return (2, 0, col)  # non-openfunds: last, alphabetical
        if match.of_id in order:
            return (0, order[match.of_id], col)
        return (1, 0, col)  # unknown OF-ID: after the catalog fields

    return sorted(present, key=key)


def header_cells(cols: list[str], catalog: OfCatalog) -> tuple[list[str], list[str]]:
    """The OF-ID row and the field name row."""
    names = []
    for col in cols:
        match = catalog.match_header(col)
        f = catalog.by_id.get(match.of_id) if match else None
        names.append(f.name if f else ("Non-openfunds Field" if match is None else ""))
    return list(cols), names


def write_openfunds(
    shareclasses: list[dict[str, str]],
    holdings: list[dict[str, str]],
    output_format: str = "xlsx",
    delimiter: str = ";",
    header_names: bool = False,
    all_columns: bool = False,
    stem: str = "openfunds",
) -> tuple[bytes, str, str]:
    """(data, filename, mime type) of the openfunds output."""
    catalog = load_openfunds()
    tables = [(SHEET_SHARECLASSES, shareclasses, ("OFST",) if all_columns else None)]
    if holdings:
        tables.append((SHEET_HOLDINGS, holdings, ("OFPH",) if all_columns else None))
    if output_format == "csv":
        files = [
            (f"{stem}_{name}.csv", _csv(rows, columns(rows, catalog, pre), catalog, delimiter, header_names))
            for name, rows, pre in tables
        ]
        if len(files) == 1:
            return files[0][1], files[0][0], "text/csv"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for name, data in files:
                zf.writestr(name, data)
        return buf.getvalue(), f"{stem}_openfunds.zip", "application/zip"
    return _xlsx(tables, catalog, header_names), f"{stem}_openfunds.xlsx", XLSX_MIME


def _xlsx(tables, catalog: OfCatalog, header_names: bool) -> bytes:
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    for name, rows, prefixes in tables:
        cols = columns(rows, catalog, prefixes)
        ws = wb.create_sheet(name)
        ids, names = header_cells(cols, catalog)
        ws.append(ids)
        if header_names:
            ws.append(names)
        types = {}
        for col in cols:
            match = catalog.match_header(col)
            f = catalog.by_id.get(match.of_id) if match else None
            types[col] = f.data_type if f else "string"
        for r in rows:
            ws.append([_cell(r.get(c, ""), types[c]) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(value: str, data_type: str):
    if not value:
        return None
    if data_type in ("double", "integer"):
        try:
            d = parse_decimal(value)
        except ValueError:
            return value
        return int(d) if d == d.to_integral_value() and abs(d) < 10**15 else float(d)
    return value


def _csv(rows, cols: list[str], catalog: OfCatalog, delimiter: str, header_names: bool) -> bytes:
    ids, names = header_cells(cols, catalog)
    buf = io.StringIO()
    if delimiter == "|":
        lines = ["|".join(ids)] + (["|".join(names)] if header_names else [])
        lines += ["|".join(r.get(c, "").replace("|", "/").replace("\n", " ") for c in cols) for r in rows]
        buf.write("\r\n".join(lines) + "\r\n")
    else:
        writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow(ids)
        if header_names:
            writer.writerow(names)
        for r in rows:
            writer.writerow([r.get(c, "") for c in cols])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
