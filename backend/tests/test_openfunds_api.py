from __future__ import annotations

import base64
import io
import zipfile

import openpyxl
import pytest

from app.service import DIRECTIONS

TARGETS = {
    "tpt_v7_sample.xlsx": ("tpt", ("fundsxml", "openfunds")),
    "fundsxml_sample.xml": ("fundsxml", ("tpt", "openfunds")),
    "openfunds_sample.xlsx": ("openfunds", ("fundsxml", "tpt")),
}


def test_six_directions():
    assert len(DIRECTIONS) == 6
    assert "openfunds-to-tpt" in DIRECTIONS and "tpt-to-openfunds" in DIRECTIONS


@pytest.mark.parametrize("name", TARGETS)
def test_every_direction(client, fixture_bytes, name):
    source, targets = TARGETS[name]
    for target in targets:
        r = client.post("/api/convert", files={"file": (name, fixture_bytes(name))}, data={"target": target})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["direction"] == f"{source}-to-{target}"
        assert body["input"]["kind"] == source
        data = base64.b64decode(body["output"]["base64"])
        if target == "fundsxml":
            assert body["validation"]["valid"] is True
            assert data.startswith(b"<?xml")
        else:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
            first = next(wb.worksheets[0].iter_rows(max_row=1, values_only=True))
            assert first[0].startswith("OF" if target == "openfunds" else "1_")


def test_default_targets(client, fixture_bytes):
    expected = {"tpt_v7_sample.xlsx": "tpt-to-fundsxml", "openfunds_sample.xlsx": "openfunds-to-fundsxml"}
    for name, direction in expected.items():
        r = client.post("/api/convert", files={"file": (name, fixture_bytes(name))})
        assert r.json()["direction"] == direction


def test_tpt_to_openfunds_keeps_tpt_fields(client, fixture_bytes):
    data = fixture_bytes("tpt_v7_sample.xlsx")
    full = client.post("/api/convert", files={"file": ("a.xlsx", data)}, data={"target": "openfunds"}).json()
    assert full["dataLoss"]["lost"] == 0
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(full["output"]["base64"])), read_only=True)
    assert wb.sheetnames == ["openfunds", "Holdings"]
    header = next(wb["Holdings"].iter_rows(max_row=1, values_only=True))
    assert any(h.startswith("TPT_") for h in header)
    plain = client.post(
        "/api/convert",
        files={"file": ("a.xlsx", data)},
        data={"target": "openfunds", "non_openfunds_columns": "false"},
    ).json()
    assert plain["dataLoss"]["lost"] > 0
    assert any(i["code"] == "hop_data_loss" for i in plain["issues"])


def test_openfunds_to_tpt_reports_what_tpt_cannot_carry(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("o.xlsx", fixture_bytes("openfunds_sample.xlsx"))},
        data={"target": "tpt", "output_format": "csv"},
    ).json()
    assert r["direction"] == "openfunds-to-tpt"
    assert r["summary"]["positions"] == 20
    loss = next(i for i in r["issues"] if i["code"] == "hop_data_loss")
    assert "OFST010010" in loss["params"]["columns"]


def test_openfunds_csv_output_with_holdings_is_zipped(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("f.xml", fixture_bytes("fundsxml_sample.xml"))},
        data={"target": "openfunds", "output_format": "csv", "response": "file"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert len(zf.namelist()) == 2


def test_target_and_direction_validation(client, fixture_bytes):
    data = fixture_bytes("openfunds_sample.xlsx")
    r = client.post("/api/convert", files={"file": ("o.xlsx", data)}, data={"target": "pdf"})
    assert r.status_code == 400
    # The browser cannot tell an openfunds from a TPT XLSX: the own format means the default target.
    r = client.post("/api/convert", files={"file": ("o.xlsx", data)}, data={"target": "openfunds"})
    assert r.json()["direction"] == "openfunds-to-fundsxml"
    r = client.post("/api/convert", files={"file": ("o.xlsx", data)}, data={"direction": "tpt-to-fundsxml"})
    assert r.status_code == 422 and "openfunds file" in r.json()["detail"]
    ok = client.post("/api/convert", files={"file": ("o.xlsx", data)}, data={"direction": "openfunds-to-tpt"})
    assert ok.status_code == 200


def test_openfunds_sample_and_mapping(client):
    assert client.get("/api/samples/openfunds").status_code == 200
    table = client.get("/api/mapping/openfunds").json()
    fields = {f["key"]: f for f in table["fields"]}
    assert table["version"] == "2.13.0"
    assert fields["OFST020000"]["status"] == "core"
    assert fields["OFPH000300"]["status"] == "holding" and fields["OFPH000300"]["holding"] == ["26"]
    assert fields["OFEM000010"]["status"] == "template"
    assert fields["OFST500010"]["status"] == "custom"
