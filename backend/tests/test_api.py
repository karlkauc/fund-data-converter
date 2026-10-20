from __future__ import annotations

import base64

BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>
<FundsXML4>&lol2;</FundsXML4>"""
XXE = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><FundsXML4>&e;</FundsXML4>"""


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_tpt_to_fundsxml(client, fixture_bytes):
    r = client.post(
        "/api/convert", files={"file": ("tpt_v7_sample.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["direction"] == "tpt-to-fundsxml"
    assert body["validation"]["valid"] is True
    assert body["summary"]["positions"] == 20
    xml = base64.b64decode(body["output"]["base64"])
    assert xml.startswith(b"<?xml") and b"<FundsXML4" in xml
    assert (
        b'xsi:noNamespaceSchemaLocation="https://github.com/fundsxml/schema/releases/download/4.2.11/FundsXML.xsd"'
        in xml
    )
    assert r.headers["cache-control"] == "no-store"


def test_fundsxml_to_tpt_csv(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("f.xml", fixture_bytes("fundsxml_sample.xml"))},
        data={"output_format": "csv", "delimiter": "pipe"},
    )
    assert r.status_code == 200
    out = base64.b64decode(r.json()["output"]["base64"]).decode("utf-8-sig")
    header = out.splitlines()[0].split("|")
    assert header[0] == "1_Portfolio_identifying_data" and len(header) == 152


def test_sample_and_mapping(client):
    assert client.get("/api/samples/tpt-v7").status_code == 200
    assert client.get("/api/samples/nope").status_code == 404
    table = client.get("/api/mapping/V8").json()
    keys = {f["key"]: f for f in table["fields"]}
    assert keys["150"]["status"] == "custom"
    assert keys["12"]["status"] == "block+core"


def test_rejects_dtd(client):
    for payload in (BOMB, XXE):
        r = client.post("/api/convert", files={"file": ("x.xml", payload)})
        assert r.status_code == 422
        assert "DOCTYPE" in r.json()["detail"]


def test_wrong_root(client):
    r = client.post("/api/convert", files={"file": ("x.xml", b"<foo/>")})
    assert r.status_code == 422


def test_bad_options(client, fixture_bytes):
    data = fixture_bytes("tpt_v7_sample.xlsx")
    assert (
        client.post("/api/convert", files={"file": ("a.xlsx", data)}, data={"tpt_version": "V9"}).status_code
        == 400
    )
    assert (
        client.post(
            "/api/convert",
            files={"file": ("a.xlsx", data)},
            data={"include_block": "false", "include_core": "false"},
        ).status_code
        == 400
    )


def test_upload_limit(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_mb", 1)
    r = client.post("/api/convert", files={"file": ("big.csv", b"x" * (3 * 1024 * 1024))})
    assert r.status_code == 413


def test_rate_limit(client, fixture_bytes, monkeypatch):
    data = b"1;6;12\nx;y;z\n"
    codes = [client.post("/api/convert", files={"file": ("a.csv", data)}).status_code for _ in range(22)]
    assert 429 in codes


def test_unknown_routes_404(client):
    assert client.get("/wp-login.php").status_code == 404
    assert client.get("/api/nope").status_code == 404


def test_xml_preview_is_cut_at_a_line_end(client, fixture_bytes, monkeypatch):
    from app import service

    monkeypatch.setattr(service, "XML_PREVIEW_BYTES", 5000)
    body = client.post(
        "/api/convert", files={"file": ("v7.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))}
    ).json()
    assert body["xmlPreviewTruncated"] is True
    assert body["xmlPreview"].endswith("\n")
    assert len(body["xmlPreview"].encode()) <= 5000
