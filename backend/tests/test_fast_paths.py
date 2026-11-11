"""The shortcuts that make large files fast give the same result as the general way.

Large openfunds files are mostly custom attributes; they are written through ``KeyedChildren``
and serialised by ``Serializer._flat``, and the second serialisation pass reuses unchanged
subtrees (``SerializeMemo``). Large XLSX files are refused by ``check_xlsx_rows`` before
openpyxl reads them.
"""

from __future__ import annotations

import csv
import io
import re

import pytest
from lxml import etree

import app.convert.openfunds_to_fundsxml as o2f
from app.config import settings
from app.convert.openfunds_to_fundsxml import convert_openfunds_to_fundsxml
from app.ingest import limits
from app.ingest.limits import TooManyRowsError, check_xlsx_rows
from app.ingest.openfunds_reader import read_openfunds
from app.ingest.tpt_reader import pick_sheet
from app.mapping.openfunds_templates import templates
from app.model import xmltree
from app.model.xmltree import KeyedChildren, Node, SerializeMemo, serialize_at
from app.schema.model import fundsxml_model
from app.service import Request, TooLargeError, convert
from app.spec.openfunds import load_openfunds


def _wide_openfunds_csv(fixture_bytes, n: int = 24) -> bytes:
    """Share classes of several funds with EMT/EET values (mostly incomplete records, so they
    end up as custom attributes), non-openfunds columns and a value the schema rejects."""
    base = [r.values for r in read_openfunds(fixture_bytes("openfunds_static.xlsx"), "s.xlsx").shareclasses]
    catalog = load_openfunds()
    fields = [f for t in templates() if t.name in ("EMT", "EET") for f in t.fields]

    def value(of_id: str, i: int) -> str:
        f = catalog.by_id.get(of_id)
        if f is None or f.data_type == "string":
            return (f.codes[0] if f and f.codes else f"text {i % 7}") if i % 5 else "  "
        return {"boolean": "yes" if i % 2 else "no", "date": "2025-12-31", "integer": str(i % 4)}.get(
            f.data_type, f"0.{i % 9}5"
        )

    rows = []
    for i in range(n):
        row = dict(base[i % len(base)])
        row["OFST020000"] = f"LU{9000000000 + i:010d}"
        row["OFST010020"] = f"Demo Fund {i // 5}"
        row["OFST010030"] = f"5299{i // 5:012d}0000"
        if i == 3:
            row["OFST020540"] = "EURO"  # not a currency: rejected, kept as custom attribute
        for j, f in enumerate(fields):
            if (i + j) % 3:
                row[f.of_id] = value(f.of_id, i + j)
        row["Note (internal)"] = f"note {i}"
        row["TPT_12_CIC_code"] = "XL41"
        rows.append(row)
    columns = list(dict.fromkeys(c for r in rows for c in r))
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(columns)
    writer.writerows([r.get(c, "") for c in columns] for r in rows)
    return buf.getvalue().encode()


def _stable(xml: bytes) -> bytes:
    return re.sub(rb"<(UniqueDocumentID|DocumentGenerated)>[^<]*<", rb"<\1>X<", xml)


class _NoMemo(SerializeMemo):
    """Keeps nothing: every pass serialises the whole tree, as before the memo."""

    def __init__(self) -> None:
        super().__init__()
        self.entries = _Forgetful()


class _Forgetful(dict):
    def __setitem__(self, key, value) -> None:
        pass


def test_openfunds_conversion_is_the_same_without_the_shortcuts(fixture_bytes, monkeypatch):
    data = _wide_openfunds_csv(fixture_bytes)
    doc = read_openfunds(data, "wide.csv")
    fast = convert_openfunds_to_fundsxml(doc)
    assert fast.stats["custom_attributes"] > 1000

    with monkeypatch.context() as m:
        m.setattr(xmltree, "_flat_plan", lambda ct, names: None)
        m.setattr(o2f, "SerializeMemo", _NoMemo)
        m.setattr(
            KeyedChildren,
            "ensure",
            lambda self, node, value: node.ensure(f"{self._container}/{self._item}[{self._key}={value}]"),
        )
        general = convert_openfunds_to_fundsxml(read_openfunds(data, "wide.csv"))

    assert _stable(fast.xml) == _stable(general.xml)
    assert [i.to_dict() for i in fast.issues] == [i.to_dict() for i in general.issues]
    assert fast.stats == general.stats
    assert (fast.valid, fast.validation_errors) == (general.valid, general.validation_errors)


def test_keyed_children_finds_what_ensure_finds():
    def tree() -> Node:
        node = Node("ShareClass")
        attr = node.ensure("CustomAttributes/Attribute[Name=OF_A]")
        attr.set("ValueText", "1")
        node.ensure("CustomAttributes").add("Attribute").add("Name").text = "OF_A"  # a second OF_A
        return node

    by_index, by_path = tree(), tree()
    index = KeyedChildren("CustomAttributes", "Attribute", "Name")
    for name in ("OF_A", "OF_B", "OF_A", "OF_B", "OF/C"):
        a = index.ensure(by_index, name)
        b = by_path.ensure(f"CustomAttributes/Attribute[Name={name}]")
        a.set("Type", "T")
        b.set("Type", "T")
    model = fundsxml_model()
    path = ["Funds", "Fund", "SingleFund", "ShareClasses", "ShareClass"]
    assert etree.tostring(serialize_at(model, by_index, path).element) == etree.tostring(
        serialize_at(model, by_path, path).element
    )
    # A name the path syntax cannot carry fails the same way.
    with pytest.raises(ValueError, match="bad path segment"):
        index.ensure(by_index, "OF_[x]")


def test_memo_redoes_what_changed_and_reuses_the_rest():
    model = fundsxml_model()

    def funds() -> tuple[Node, list[Node]]:
        root = Node("Funds")
        classes = []
        for i in range(3):
            fund = root.add("Fund")
            fund.set("Names/OfficialName", f"Fund {i}")
            fund.set("Currency", "EUR")
            fund.set("SingleFundFlag", "true")
            sc = fund.ensure("SingleFund/ShareClasses").add("ShareClass")
            sc.set("Identifiers/ISIN", f"LU000000000{i}")
            sc.set("Names/OfficialName", f"Class {i}")
            sc.set("Currency", "XX")  # rejected: reported in both passes
            sc.set("LiquidationReason", "merger", "1:x")  # written as MERGER: reported in both passes
            classes.append(sc)
        return root, classes

    def add_customs(classes: list[Node], index: KeyedChildren) -> None:
        for n, sc in enumerate(classes[:2]):
            for k in range(3):
                attr = index.ensure(sc, f"OF_{k}")
                attr.set("Type", "T")
                attr.set("ValueText", f"{n}-{k}")

    memo = SerializeMemo()
    tree, classes = funds()
    first = serialize_at(model, tree, ["Funds"], memo)
    index = KeyedChildren("CustomAttributes", "Attribute", "Name")
    add_customs(classes, index)
    memo.forget(index.changed())
    again = serialize_at(model, tree, ["Funds"], memo)

    fresh_tree, fresh_classes = funds()
    add_customs(fresh_classes, KeyedChildren("CustomAttributes", "Attribute", "Name"))
    fresh = serialize_at(model, fresh_tree, ["Funds"])

    assert etree.tostring(again.element) == etree.tostring(fresh.element)
    for kind in ("dropped", "invalid", "changed"):
        assert getattr(again, kind) == getattr(fresh, kind)
    assert first.invalid and first.invalid == fresh.invalid
    assert len(first.changed) == 3 and first.changed == fresh.changed
    assert b"OF_2" in etree.tostring(again.element)


def _sheet(rows: int, numbers: bool = True, blank_gap: int = 0) -> bytes:
    """An XLSX as some exporters write it: inline strings, no stored dimension. Without numbers
    the rows hold only blanks, which the reader counts as values and the check does not."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("TPT")
    ws.append(["1_Portfolio_identifying_data", "12_CIC_code_of_the_instrument", "24_Market_valuation"])
    for i in range(rows):
        if i == rows // 2:
            for _ in range(blank_gap):
                ws.append([])
        ws.append([f"P{i}", "XT72", i] if numbers else ["  "] * 3)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def small_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_positions", 20)
    monkeypatch.setattr(limits, "ROW_SLACK", 5)


def _no_openpyxl_reading(monkeypatch):
    import openpyxl

    def refuse(*args, **kwargs):
        raise AssertionError("the workbook was read")

    monkeypatch.setattr(openpyxl, "load_workbook", refuse)
    monkeypatch.setattr(openpyxl.reader.excel, "load_workbook", refuse)


def test_xlsx_with_too_many_rows_is_refused_before_it_is_read(small_limit, monkeypatch):
    data = _sheet(40)
    _no_openpyxl_reading(monkeypatch)
    with pytest.raises(TooLargeError, match="more than 20 positions"):
        convert(Request(data, "big.xlsx", preview=False))
    with pytest.raises(TooManyRowsError):
        check_xlsx_rows(data, pick_sheet)


def test_xlsx_row_check_only_refuses_what_the_reader_refuses(small_limit):
    # Within the limit, or rows past a blank run (where the table ends): not refused here.
    check_xlsx_rows(_sheet(20), pick_sheet)
    check_xlsx_rows(_sheet(40, blank_gap=limits.BLANK_RUN + 1), pick_sheet)
    # Values that may count as blank leave the decision to the reader, which refuses.
    texts = _sheet(40, numbers=False)
    check_xlsx_rows(texts, pick_sheet)
    with pytest.raises(TooLargeError, match="more than 20 positions"):
        convert(Request(texts, "big.xlsx", preview=False))
