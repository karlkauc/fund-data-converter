"""Converted files say where they come from: an XML comment in FundsXML, document properties in XLSX."""

from __future__ import annotations

import io

from lxml import etree
from openpyxl import load_workbook

from app import release_version
from app.service import Request, convert
from app.writers.provenance import APP_NAME, Provenance, with_xml_comment


def _comment(xml: bytes) -> str:
    root = etree.fromstring(xml)
    comments = [c for c in root.itersiblings(preceding=True) if isinstance(c, etree._Comment)]
    assert len(comments) == 1
    return comments[0].text


def test_fundsxml_names_tool_time_source_and_contents(fixture_bytes):
    report, out = convert(Request(fixture_bytes("tpt_v7_sample.xlsx"), "fund.xlsx", preview=False))
    assert out.data.startswith(b"<?xml")
    text = _comment(out.data)
    assert f"{APP_NAME} {release_version()}" in text
    assert "Source file:    fund.xlsx" in text
    assert "Conversion:     TPT V7 → FundsXML 4." in text
    assert "positions" in text and "Converted at:" in text and "automatically" in text
    assert report["validation"]["valid"]


def test_openfunds_to_fundsxml_has_the_comment_too(fixture_bytes):
    _report, out = convert(Request(fixture_bytes("openfunds_sample.xlsx"), "of.xlsx", target="fundsxml"))
    assert "openfunds → FundsXML" in _comment(out.data)


def test_xlsx_outputs_carry_document_properties(fixture_bytes):
    for data, name, target, conversion in (
        (fixture_bytes("fundsxml_sample.xml"), "a.xml", "tpt", "FundsXML → TPT V"),
        (fixture_bytes("tpt_v7_sample.xlsx"), "b.xlsx", "openfunds", "TPT V7 → openfunds "),
    ):
        _report, out = convert(Request(data, name, target=target))
        wb = load_workbook(io.BytesIO(out.data), read_only=True)
        props = wb.properties
        assert props.creator == APP_NAME
        assert props.subject.startswith(conversion)
        assert f"Source file: {name}" in props.description
        assert props.created is not None
        custom = {p.name: p.value for p in wb.custom_doc_props.props}
        assert custom["Source file"] == name and custom["Conversion"].startswith(conversion)


def test_csv_output_stays_plain(fixture_bytes):
    _report, out = convert(Request(fixture_bytes("fundsxml_sample.xml"), "a.xml", output_format="csv"))
    assert APP_NAME.encode() not in out.data


def test_comment_text_cannot_end_the_comment():
    prov = Provenance("evil-->--name-.xlsx", "TPT V7", "FundsXML 4.2.11")
    xml = with_xml_comment(b"<?xml version='1.0' encoding='UTF-8'?>\n<FundsXML4/>", prov)
    assert "evil- ->- -name-.xlsx" in _comment(xml)
