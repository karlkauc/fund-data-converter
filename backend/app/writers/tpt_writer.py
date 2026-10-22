"""Write TPT rows as XLSX or delimited text, columns in spec order."""

from __future__ import annotations

import csv
import io

from app.model.xmltree import parse_decimal
from app.spec.catalog import Catalog, load_catalog
from app.writers.xlsx_numbers import full_precision_floats

CSV_DELIMITERS = {"semicolon": ";", "comma": ",", "pipe": "|", "tab": "\t"}


def _columns(catalog: Catalog, rows: list[dict[str, str]], all_columns: bool) -> list[str]:
    if all_columns:
        return catalog.key_order()
    present = {k for r in rows for k in r}
    return [k for k in catalog.key_order() if k in present]


def write_xlsx(rows: list[dict[str, str]], version: str, all_columns: bool = True) -> bytes:
    from openpyxl import Workbook

    full_precision_floats()
    catalog = load_catalog(version)
    keys = _columns(catalog, rows, all_columns)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(f"TPT {version}.0")
    ws.append([catalog.by_key[k].num_data for k in keys])
    numeric = {k for k in keys if catalog.by_key[k].kind == "NUMERIC"}
    for r in rows:
        ws.append([_cell(r.get(k, ""), k in numeric) for k in keys])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cell(value: str, numeric: bool):
    if not value:
        return None
    if numeric:
        try:
            d = parse_decimal(value)
        except ValueError:
            return value
        return int(d) if d == d.to_integral_value() and abs(d) < 10**15 else float(d)
    return value


def write_csv(
    rows: list[dict[str, str]], version: str, delimiter: str = ";", all_columns: bool = True, bom: bool = True
) -> bytes:
    catalog = load_catalog(version)
    keys = _columns(catalog, rows, all_columns)
    buf = io.StringIO()
    if delimiter == "|":
        # Pipe files are unquoted by convention; strip the delimiter from values instead.
        lines = ["|".join(catalog.by_key[k].num_data for k in keys)]
        lines += ["|".join(r.get(k, "").replace("|", "/").replace("\n", " ") for k in keys) for r in rows]
        buf.write("\r\n".join(lines) + "\r\n")
    else:
        writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow([catalog.by_key[k].num_data for k in keys])
        for r in rows:
            writer.writerow([r.get(k, "") for k in keys])
    data = buf.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data
