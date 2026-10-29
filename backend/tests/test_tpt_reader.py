from __future__ import annotations

import pytest

from app.ingest.tpt_reader import TptReadError, detect_version, read_tpt
from app.writers.tpt_writer import write_xlsx

HEADER = [
    "1_Portfolio_identifying_data",
    "6_Valuation_date",
    "12_CIC_code_of_the_instrument",
    "14_Identification_code_of_the_instrument",
    "1000_TPT_Version",
]
ROW = ["FR0010000001", "2025-12-31", "FR12", "FR0000571085", "V7.0 (official) dated 25 November 2024"]


def _csv(delim: str, header=HEADER, row=ROW, prefix: str = "") -> bytes:
    return (prefix + delim.join(header) + "\n" + delim.join(row) + "\n").encode("utf-8")


@pytest.mark.parametrize("delim", [";", ",", "|", "\t"])
def test_delimiters_are_detected(delim):
    doc = read_tpt(_csv(delim), "x.csv")
    assert doc.delimiter == delim
    assert doc.rows[0].get("12") == "FR12"
    assert doc.version == "V7"


def test_bom_sep_hint_and_late_header():
    data = b"\xef\xbb\xbf" + _csv(";", prefix="sep=;\nsome title\n\n\n")
    doc = read_tpt(data, "x.csv")
    assert doc.keys == ["1", "6", "12", "14", "1000"]
    assert doc.rows[0].source_row == 5


def test_bare_numbers_and_loose_names_match():
    header = ["1", "6", "12_CIC", "Identification code of the instrument", "1000"]
    doc = read_tpt(_csv(";", header=header), "x.csv")
    assert doc.keys == ["1", "6", "12", "14", "1000"]


def test_unknown_columns_are_reported():
    doc = read_tpt(_csv(";", header=HEADER + ["My own column"], row=ROW + ["x"]), "x.csv")
    assert doc.unmapped_headers == ["My own column"]
    assert any(i.code == "unmapped_columns" for i in doc.issues)


def test_no_header_raises():
    with pytest.raises(TptReadError):
        read_tpt(b"foo;bar;baz\nx;y;z\n", "x.csv")


def test_xlsx_fixture(fixture_bytes):
    doc = read_tpt(fixture_bytes("00_showcase.xlsx"), "00_showcase.xlsx")
    assert (doc.version, doc.file_format, len(doc.rows)) == ("V7", "xlsx", 60)


def test_version_detection():
    from app.ingest.tpt_reader import TptRow

    assert detect_version([TptRow({"1000": "V8.0 (official) dated 8 October 2026"}, 2)], set()) == (
        "V8",
        "field 1000",
    )
    assert detect_version([TptRow({"1000": "V7.0 dated 18 Nov 2024"}, 2)], set())[0] == "V7"
    assert detect_version([TptRow({"1": "x"}, 2)], {"150"}) == ("V8", "fields 150/151")
    assert detect_version([TptRow({"1": "x"}, 2)], set()) == ("V7", "default")


def test_version_can_be_forced():
    assert read_tpt(_csv(";"), "x.csv", version="v8").version == "V8"


def test_xlsx_numbers_keep_full_precision():
    """openpyxl alone writes "%.16g" and drops the 17th digit a double may need."""
    rows = [{"1": "AT0000000001", "9": "1.8931484249581674", "26": "0.12345678901234567"}]
    back = read_tpt(write_xlsx(rows, "V7"), "x.xlsx").rows[0]
    assert back.get("9") == "1.8931484249581674"
    assert float(back.get("26")) == float("0.12345678901234567")
