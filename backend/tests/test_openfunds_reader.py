import io
import zipfile

import pytest

from app.ingest.openfunds_reader import OpenfundsReadError, looks_like_openfunds, read_openfunds
from app.writers.openfunds_writer import write_openfunds

SHARECLASSES = [
    {
        "OFST020000": "LU0000000001",
        "OFST010020": "Demo Fund - Bonds",
        "OFST020540": "EUR",
        "OFST020400": "distributing",
        "OFST010010": "LU",
        "OFST6030AT": "yes",
        "OFST001000(de)": "Demo Fondsgruppe",
        "My Internal Rating": "A",
    },
    {"OFST020000": "LU0000000002", "OFST010020": "Demo Fund - Bonds", "OFST020540": "USD"},
]
HOLDINGS = [
    {
        "OFST020000": "LU0000000001",
        "OFPH000010": "2025-12-31",
        "OFPH000100": "DE0001102580",
        "OFPH000300": "0.25",
    },
    {
        "OFST020000": "LU0000000001",
        "OFPH000010": "2025-12-31",
        "OFPH000200": "Cash EUR",
        "OFPH000300": "0.75",
    },
]


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
@pytest.mark.parametrize("names", [False, True])
def test_write_read_roundtrip(fmt, names):
    data, filename, _ = write_openfunds(SHARECLASSES, HOLDINGS, fmt, ";", header_names=names)
    assert looks_like_openfunds(data, filename)
    doc = read_openfunds(data, filename)
    assert [r.values | r.extra for r in doc.shareclasses] == SHARECLASSES
    assert [r.values for r in doc.holdings] == HOLDINGS
    assert doc.layout == "flat"
    codes = {i.code for i in doc.issues}
    assert "of_non_openfunds_column" in codes
    assert "of_value_invalid" not in codes


def test_csv_without_holdings_is_plain_csv():
    data, filename, mime = write_openfunds(SHARECLASSES, [], "csv")
    assert mime == "text/csv" and filename.endswith(".csv")
    assert data.startswith(b"\xef\xbb\xbfOFST001000(de);OFST010010;")


def test_columns_in_catalog_order():
    data, filename, _ = write_openfunds(SHARECLASSES, [], "csv", ",")
    header = data.decode("utf-8-sig").splitlines()[0].split(",")
    assert header == [
        "OFST001000(de)",
        "OFST010010",
        "OFST010020",
        "OFST020000",
        "OFST020400",
        "OFST020540",
        "OFST6030AT",
        "My Internal Rating",
    ]


def test_narrow_layouts_are_merged():
    csv = (
        b"OFST020000;OFST600000;OFST6030XX;OFST020540\n"
        b"LU0000000001;AT;yes;EUR\n"
        b"LU0000000001;DE;no;EUR\n"
        b"OFST020000;OFDY100000;OFDY100100;OFDY100110;OFDY100111\n"
    )
    doc = read_openfunds(csv, "narrow.csv")
    assert doc.layout == "narrow"
    assert doc.shareclasses[0].values == {
        "OFST020000": "LU0000000001",
        "OFST6030AT": "yes",
        "OFST6030DE": "no",
        "OFST020540": "EUR",
    }


def test_dynamic_narrow():
    csv = (
        b"OFST020000;OFDY100000;OFDY100100;OFDY100110;OFDY100111\n"
        b"LU0000000001;2025-12-31;OFDY000035;EUR;101.5\n"
        b"LU0000000001;2025-12-31;OFDY000070;EUR;1000000\n"
    )
    doc = read_openfunds(csv, "dyn.csv")
    assert doc.shareclasses[0].values == {
        "OFST020000": "LU0000000001",
        "OFDY100000": "2025-12-31",
        "OFDY000035": "101.5",
        "OFDY000010": "EUR",
        "OFDY000070": "1000000",
    }


def test_conflicts_ignore_and_invalid_values():
    csv = (
        b"OFST020000;OFST020540;OFST010240;OFST020400;OFST999999\n"
        b"LU0000000001;EUR;2020-13-45;sometimes;x\n"
        b"LU0000000001;USD;[IGNORE];;\n"
    )
    doc = read_openfunds(csv, "bad.csv")
    codes = [i.code for i in doc.issues]
    assert "of_value_conflict" in codes
    assert "of_ignore_value" in codes
    assert codes.count("of_value_invalid") == 2  # date and code list


def test_unknown_and_revoked_ids_are_reported():
    csv = b"OFST020000;OFST020540;OFST029999\nLU0000000001;EUR;x\n"
    doc = read_openfunds(csv, "x.csv")
    assert any(i.code == "of_unknown_field" for i in doc.issues)
    assert doc.shareclasses[0].values["OFST029999"] == "x"


def test_zip_of_csv_files():
    data, filename, mime = write_openfunds(SHARECLASSES, HOLDINGS, "csv")
    assert mime == "application/zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["openfunds_Holdings.csv", "openfunds_openfunds.csv"]
    doc = read_openfunds(data, filename)
    assert doc.file_format == "zip" and len(doc.holdings) == 2


def test_tpt_file_is_not_openfunds(fixture_bytes):
    data = fixture_bytes("01_clean.xlsx")
    assert not looks_like_openfunds(data, "01_clean.xlsx")
    with pytest.raises(OpenfundsReadError):
        read_openfunds(data, "01_clean.xlsx")
