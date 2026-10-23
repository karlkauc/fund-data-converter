from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

import openpyxl
from lxml import etree

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
    answers = [client.post("/api/convert", files={"file": ("a.csv", data)}) for _ in range(22)]
    codes = [r.status_code for r in answers]
    assert codes.index(429) == 20  # 20 per minute, whatever the outcome of the conversion
    first, refused = answers[0], answers[20]
    assert first.headers["X-RateLimit-Limit-Minute"] == "20"
    assert first.headers["X-RateLimit-Remaining-Minute"] == "19"
    assert first.headers["X-RateLimit-Limit-Hour"] == "200"
    assert first.headers["X-RateLimit-Remaining-Hour"] == "199"
    assert refused.headers["X-RateLimit-Remaining-Minute"] == "0"
    assert refused.headers["X-RateLimit-Remaining-Hour"] == "180"  # a refused request does not count
    assert 0 < int(refused.headers["Retry-After"]) <= 60
    assert "20 per minute, 200 per hour" in refused.json()["detail"]


def test_rate_limit_is_reported(client, fixture_bytes):
    before = client.get("/api/limits").json()["convert"]
    assert before == [
        {"window": "minute", "limit": 20, "remaining": 20, "resetSeconds": 0},
        {"window": "hour", "limit": 200, "remaining": 200, "resetSeconds": 0},
    ]
    sample = {"file": ("tpt_v7_sample.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))}
    r = client.post("/api/convert", files=sample)
    windows = r.json()["rateLimit"]
    assert [(w["window"], w["remaining"]) for w in windows] == [("minute", 19), ("hour", 199)]
    assert 0 < windows[0]["resetSeconds"] <= 60
    # Asking costs nothing.
    assert [w["remaining"] for w in client.get("/api/limits").json()["convert"]] == [19, 199]
    file = client.post(
        "/api/convert",
        files={"file": ("tpt_v7_sample.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))},
        data={"response": "file"},
    )
    assert file.headers["X-RateLimit-Remaining-Minute"] == "18"


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


def _report_header(r) -> dict:
    raw = r.headers["x-conversion-report"]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


def test_json_report_has_counts_data_loss_and_meta(client, fixture_bytes):
    data = fixture_bytes("tpt_v7_sample.xlsx")
    body = client.post("/api/convert", files={"file": ("a.xlsx", data)}).json()
    assert body["output"]["base64"] and body["preview"]["rows"] and body["xmlPreview"]
    out = base64.b64decode(body["output"]["base64"])
    assert body["output"]["sha256"] == hashlib.sha256(out).hexdigest()
    assert sum(body["issueCounts"].values()) == len(body["issues"])
    assert body["dataLoss"] == {
        "lost": 0,
        "keptAsCustomAttribute": 3,
        "notInCoreStructures": 0,
        "codes": ["block_value_rejected"],
    }
    meta = body["meta"]
    assert meta["fundsxmlSchema"] == "4.2.11" and meta["converterVersion"]
    assert meta["input"] == {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    assert meta["durationMs"] >= 0


def test_data_loss_without_core_structures(client, fixture_bytes):
    body = client.post(
        "/api/convert",
        files={"file": ("a.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))},
        data={"include_core": "false", "preview": "false"},
    ).json()
    assert body["dataLoss"]["lost"] == 3 and body["dataLoss"]["keptAsCustomAttribute"] == 0
    assert "preview" not in body and "xmlPreview" not in body


def test_response_file_tpt_to_fundsxml(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("my fund.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))},
        data={"response": "file"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert r.headers["content-disposition"] == 'attachment; filename="my_fund_FundsXML.xml"'
    assert r.content.startswith(b"<?xml") and b"<FundsXML4" in r.content
    assert r.headers["x-conversion-direction"] == "tpt-to-fundsxml"
    assert r.headers["x-conversion-valid"] == "true"
    assert r.headers["x-conversion-positions"] == "20"
    assert r.headers["x-conversion-data-lost"] == "0"
    assert "block_value_rejected" in r.headers["x-conversion-issue-codes"].split(",")
    assert "X-Conversion-Report" in r.headers["access-control-expose-headers"]
    report = _report_header(r)
    assert report["output"]["sha256"] == hashlib.sha256(r.content).hexdigest()
    assert "portfolioList" not in report["summary"] and "fields" not in report["coverage"]


def test_response_file_fundsxml_to_tpt(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("f.xml", fixture_bytes("fundsxml_sample.xml"))},
        data={"response": "file"},
    )
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('_TPT_V7.xlsx"')
    assert openpyxl.load_workbook(io.BytesIO(r.content)).active.max_row > 1
    assert r.headers["x-conversion-valid"] == "" and r.headers["x-conversion-data-lost"] == ""
    assert _report_header(r)["validation"] is None


def test_response_zip_bundles_file_report_and_issues(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("a.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))},
        data={"response": "zip"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="a_FundsXML_conversion.zip"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == ["a_FundsXML.xml", "issues.csv", "report.json"]
        report = json.loads(zf.read("report.json"))
        issues = zf.read("issues.csv").decode("utf-8-sig").splitlines()
        xml = zf.read("a_FundsXML.xml")
    assert "base64" not in report["output"] and "preview" not in report
    assert report["output"]["sha256"] == hashlib.sha256(xml).hexdigest()
    assert issues[0] == "level;code;field;row;path;value;message"
    assert len(issues) == 1 + len(report["issues"])


def test_zip_bundle_holds_the_unzipped_file(client, fixture_bytes, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "zip_threshold_mb", 0)
    data = fixture_bytes("tpt_v7_sample.xlsx")
    json_body = client.post("/api/convert", files={"file": ("a.xlsx", data)}).json()
    assert json_body["output"]["zipped"] is True and json_body["output"]["filename"] == "a_FundsXML.xml.zip"
    r = client.post("/api/convert", files={"file": ("a.xlsx", data)}, data={"response": "zip"})
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read("a_FundsXML.xml").startswith(b"<?xml")


def test_direction_option(client, fixture_bytes):
    tpt = fixture_bytes("tpt_v7_sample.xlsx")
    ok = client.post("/api/convert", files={"file": ("a.xlsx", tpt)}, data={"direction": "tpt-to-fundsxml"})
    assert ok.status_code == 200
    r = client.post("/api/convert", files={"file": ("a.xlsx", tpt)}, data={"direction": "fundsxml-to-tpt"})
    assert r.status_code == 422 and "TPT file" in r.json()["detail"]
    r = client.post("/api/convert", files={"file": ("a.xlsx", tpt)}, data={"direction": "sideways"})
    assert r.status_code == 400


def test_bad_response_mode(client, fixture_bytes):
    data = fixture_bytes("tpt_v7_sample.xlsx")
    r = client.post("/api/convert", files={"file": ("a.xlsx", data)}, data={"response": "pdf"})
    assert r.status_code == 400 and "response" in r.json()["detail"]


def test_data_supplier_overrides(client, fixture_bytes):
    r = client.post(
        "/api/convert",
        files={"file": ("a.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))},
        data={
            "response": "file",
            "data_supplier_name": "Example Asset Management",
            "data_supplier_short": "EXAM",
            "data_supplier_country": "at",
        },
    )
    supplier = etree.fromstring(r.content).find("ControlData/DataSupplier")
    assert supplier.findtext("Name") == "Example Asset Management"
    assert supplier.findtext("Short") == "EXAM"
    assert supplier.findtext("SystemCountry") == "AT"


def test_openapi_documents_the_convert_options(client):
    spec = client.get("/api/openapi.json").json()
    op = spec["paths"]["/api/convert"]["post"]
    ref = op["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[1]
    props = spec["components"]["schemas"][ref]["properties"]
    assert {"response", "direction", "preview", "data_supplier_name"} <= set(props)
    content = set(op["responses"]["200"]["content"])
    assert content == {"application/json", "application/octet-stream", "application/zip"}


def test_swagger_ui_may_load_its_bundle(client):
    csp = client.get("/api/docs").headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp and "sandbox" not in csp
    assert "sandbox" in client.get("/api/health").headers["content-security-policy"]


def test_fundsxml_schema_zip_for_the_xml_viewer(client):
    r = client.get("/api/schema/fundsxml.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "max-age" in r.headers["cache-control"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["FundsXML4.xsd", "xmldsig-core-schema.xsd"]
        # The main schema imports the signature schema by this relative name.
        assert b'schemaLocation="xmldsig-core-schema.xsd"' in zf.read("FundsXML4.xsd")
    again = client.get("/api/schema/fundsxml.zip", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and not again.content


def test_bare_domain_redirects_to_www(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "_apex_host", "fund-data-converter.eu")
    monkeypatch.setattr(main.settings, "site_origin", "https://www.fund-data-converter.eu")
    r = client.get("/mapping?x=1", headers={"host": "fund-data-converter.eu"}, follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "https://www.fund-data-converter.eu/mapping?x=1"
    r = client.post("/api/convert", headers={"host": "fund-data-converter.eu"}, follow_redirects=False)
    assert r.status_code == 308
    assert client.get("/api/health").status_code == 200
