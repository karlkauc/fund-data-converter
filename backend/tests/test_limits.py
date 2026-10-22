"""Uploads that are small on the wire but huge once read, and values that would run as formulas."""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from app.config import settings
from app.ingest.openfunds_reader import OpenfundsReadError, looks_like_openfunds, read_openfunds
from app.ingest.tpt_reader import TptReadError, read_tpt
from app.service import Request, TooLargeError, convert, detect_kind
from app.writers.formula_safe import csv_text
from app.writers.tpt_writer import write_csv, write_xlsx


def _zip(name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def test_sparse_sheet_is_not_read_cell_by_cell():
    """One cell in A1 and one in XFD1048576: a few KB that would be 17 billion cells."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.active["A1"] = "x"
    wb.active["XFD1048576"] = "y"
    buf = io.BytesIO()
    wb.save(buf)
    start = time.perf_counter()
    with pytest.raises(TptReadError, match="no TPT header"):
        read_tpt(buf.getvalue(), "sparse.xlsx")
    assert time.perf_counter() - start < 10


def test_csv_of_blank_lines_ends_the_table():
    start = time.perf_counter()
    with pytest.raises(TptReadError):
        read_tpt(b"\n" * (5 * 1024 * 1024), "blank.csv")
    assert time.perf_counter() - start < 10


def test_more_rows_than_positions_is_too_large(fixture_bytes, monkeypatch):
    from app.ingest import limits

    monkeypatch.setattr(settings, "max_positions", 3)
    monkeypatch.setattr(limits, "ROW_SLACK", 2)
    for name in ("tpt_v7_sample.xlsx", "tpt_semicolon.csv", "openfunds_sample.xlsx"):
        with pytest.raises(TooLargeError, match="more than 3 positions"):
            convert(Request(fixture_bytes(name), name, preview=False))


def test_zip_bomb_is_refused_before_unpacking():
    bomb = _zip("holdings.csv", b"\n" * (20 * 1024 * 1024))
    assert len(bomb) < 100 * 1024
    assert not looks_like_openfunds(bomb, "of.zip")
    assert detect_kind(bomb, "of.zip") == "tpt"
    with pytest.raises(OpenfundsReadError, match="unpacks to 20 MB"):
        read_openfunds(bomb, "of.zip")


def test_bundled_zip_still_reads(fixture_bytes):
    doc = read_openfunds(fixture_bytes("openfunds_csv.zip"), "openfunds_csv.zip")
    assert doc.holdings


def test_xml_with_too_many_tags_is_refused(fixture_bytes, monkeypatch):
    from app import service

    monkeypatch.setattr(service, "MAX_XML_TAGS", 100)
    with pytest.raises(TooLargeError, match="more than 100 tags"):
        convert(Request(fixture_bytes("fundsxml_sample.xml"), "a.xml", preview=False))


def test_text_starting_with_equals_is_no_formula_in_xlsx():
    rows = [{"1": "LU0000000001", "17": '=HYPERLINK("https://evil.example","x")', "24": "-5"}]
    data = write_xlsx(rows, "V7")
    sheet = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml")
    assert b"<f>" not in sheet
    back = read_tpt(data, "a.xlsx").rows[0]
    assert back.get("17") == rows[0]["17"]
    assert back.get("24") == "-5"


def test_formula_text_is_quoted_in_csv():
    assert csv_text("=1+1") == "'=1+1"
    assert csv_text("@SUM(A1)") == "'@SUM(A1)"
    assert csv_text('+HYPERLINK("x")') == '\'+HYPERLINK("x")'
    for kept in ("-1.5", "+2", "-", "", "Bund 2030", "a=b"):
        assert csv_text(kept) == kept
    out = write_csv([{"1": "x", "17": "=cmd|' /C calc'!A0", "24": "-12.5"}], "V7").decode("utf-8-sig")
    assert ";'=cmd" in out and ";-12.5" in out


def test_issues_csv_quotes_formulas():
    from app.api.convert import _issues_csv

    text = _issues_csv([{"level": "error", "code": "x", "value": "=1+1", "row": 3}]).decode("utf-8-sig")
    assert "'=1+1" in text and ";3;" in text


def test_ipv6_clients_share_their_64():
    from starlette.requests import Request as HttpRequest

    from app.rate_limit import visitor_key

    def key(ip: str) -> str:
        return visitor_key(HttpRequest({"type": "http", "headers": [(b"x-forwarded-for", ip.encode())]}))

    assert key("2001:db8:1:2:aaaa::1") == key("2001:db8:1:2:bbbb::2") == "2001:db8:1:2::/64"
    assert key("2001:db8:1:3::1") != key("2001:db8:1:2::1")
    assert key("203.0.113.7") == "203.0.113.7"
    assert key("::ffff:203.0.113.7") == "203.0.113.7"


def test_busy_converter_answers_503(client, monkeypatch):
    monkeypatch.setattr(settings, "max_pending_conversions", 0)
    r = client.post("/api/convert", files={"file": ("a.csv", b"1;6;12\nx;y;z\n")})
    assert r.status_code == 503
    assert r.headers["Retry-After"]
    # A refusal costs no quota.
    assert client.get("/api/limits").json()["convert"][0]["remaining"] == 20


def test_exhausted_quota_is_refused_before_the_upload(client, monkeypatch):
    from app.rate_limit import convert_quota

    monkeypatch.setattr(convert_quota, "exhausted", lambda _key: True)
    r = client.post("/api/convert", files={"file": ("a.csv", b"x" * 1024)})
    assert r.status_code == 429
    assert r.headers["X-RateLimit-Limit-Minute"] == "20"
