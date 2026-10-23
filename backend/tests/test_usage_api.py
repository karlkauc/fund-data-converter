"""Which requests emit which usage events – and that no file data leaks into them."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.usage.context import UsageTracker
from app.usage.events import UsageEvent
from app.usage.recorder import UsageRecorder


class ListRecorder(UsageRecorder):
    def __init__(self) -> None:
        super().__init__("postgresql://fake")
        self.events: list[UsageEvent] = []

    def record(self, event: UsageEvent) -> bool:
        self.events.append(event)
        return True


@pytest.fixture
def events(client) -> list[UsageEvent]:
    recorder = ListRecorder()
    client.app.state.usage = UsageTracker(recorder, geoip=None, hash_secret="s", instance="test")
    return recorder.events


def _post(client, name: str, data: bytes, **form):
    return client.post("/api/convert", files={"file": (name, data)}, data=form)


def test_convert_tpt_event(client, events, fixture_bytes):
    data = fixture_bytes("01_clean.xlsx")
    assert _post(client, "Secret Fund 2026.xlsx", data).status_code == 200
    (ev,) = events
    assert ev.event_type == "convert" and ev.status == "ok" and ev.status_code == 200
    assert ev.direction == "tpt-to-fundsxml" and ev.output_format == "xml"
    assert ev.source == "xlsx" and ev.schema_name == f"TPT {ev.tpt_version}"
    assert ev.target_namespace == "FundsXML 4"
    assert ev.input_bytes == len(data) and ev.element_count and ev.file_count and ev.type_count
    assert ev.include_block is True and ev.include_core is True
    assert isinstance(ev.valid, bool) and ev.zipped is False and ev.duration_ms is not None
    assert ev.instance == "test" and ev.visitor_hash and ev.app_version
    assert ev.issue_codes == sorted(set(ev.issue_codes))
    assert ev.delimiter is None and ev.all_columns is None


def test_convert_event_records_output_size(client, events, fixture_bytes):
    body = _post(client, "a.xlsx", fixture_bytes("01_clean.xlsx")).json()
    assert events[0].output_bytes == body["output"]["size"] > 0


def test_convert_tpt_csv_records_detected_delimiter(client, events, fixture_bytes):
    _post(client, "m.csv", fixture_bytes("02_missing_mandatory.csv"))
    (ev,) = events
    assert ev.source == "csv" and ev.delimiter == "semicolon"
    assert ev.all_columns is None


def test_convert_event_carries_no_file_data(client, events, fixture_bytes):
    body = _post(client, "Secret Fund 2026.xlsx", fixture_bytes("01_clean.xlsx")).json()
    row = repr(dataclasses.astuple(events[0]))
    assert "Secret" not in row
    for p in body["summary"]["portfolioList"]:
        for value in (p["id"], p["name"], p["nav"]):
            if value:
                assert value not in row
    for issue in body["issues"]:
        assert issue["message"] not in row


def test_convert_fundsxml_event(client, events, fixture_bytes):
    r = _post(client, "f.xml", fixture_bytes("fundsxml_sample.xml"), output_format="csv")
    assert r.status_code == 200
    (ev,) = events
    assert ev.direction == "fundsxml-to-tpt" and ev.output_format == "csv"
    assert ev.source == "sample" and ev.schema_name == "FundsXML 4"
    assert ev.target_namespace == f"TPT {ev.tpt_version}" and ev.valid is None
    assert ev.include_block is None and ev.type_count is None
    assert ev.delimiter == "semicolon" and ev.all_columns is True
    assert ev.output_bytes == r.json()["output"]["size"] > 0


@pytest.mark.parametrize(
    ("form", "delimiter", "all_columns"),
    [
        ({"output_format": "csv", "delimiter": "Tab", "all_columns": "false"}, "tab", False),
        ({"output_format": "csv", "delimiter": "nonsense"}, "semicolon", True),
        ({"output_format": "xlsx", "delimiter": "comma", "all_columns": "0"}, None, False),
    ],
)
def test_convert_fundsxml_options_are_recorded(client, events, fixture_bytes, form, delimiter, all_columns):
    assert _post(client, "f.xml", fixture_bytes("fundsxml_sample.xml"), **form).status_code == 200
    (ev,) = events
    assert (ev.delimiter, ev.all_columns) == (delimiter, all_columns) and ev.output_bytes


def test_sample_upload_is_marked(client, events, fixture_bytes):
    _post(client, "tpt_v7_sample.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))
    assert events[0].source == "sample"


def test_parse_error_keeps_only_the_exception_class(client, events):
    assert _post(client, "x.xml", b"<foo>Secret Fund</foo>").status_code == 422
    (ev,) = events
    assert ev.status == "parse_error" and ev.status_code == 422
    assert ev.error_detail == "FundsXmlReadError" and ev.direction == "fundsxml-to-tpt"
    assert ev.source == "xml" and ev.tpt_version is None
    assert "Secret" not in repr(dataclasses.astuple(ev))


@pytest.mark.parametrize(
    ("name", "source"),
    [("a.xlsx", "xlsx"), ("a.XLS", "xlsx"), ("a.csv", "csv"), ("a.xml", "xml"), ("a.txt", None)],
)
def test_failed_conversion_keeps_version_and_source(client, events, name, source):
    assert _post(client, name, b"Secret Fund;1;2\n", tpt_version="v8").status_code == 422
    (ev,) = events
    assert ev.status == "parse_error" and ev.tpt_version == "V8" and ev.source == source
    assert ev.input_bytes == len(b"Secret Fund;1;2\n")


def test_failed_conversion_of_a_sample_is_marked(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_positions", 1)
    assert _post(client, "x.xlsx", fixture_bytes("tpt_v7_sample.xlsx")).status_code == 422
    assert events[0].source == "sample" and events[0].tpt_version is None


def test_too_many_positions_is_rejected(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_positions", 1)
    assert _post(client, "a.xlsx", fixture_bytes("tpt_v7_sample.xlsx")).status_code == 422
    assert events[0].status == "rejected" and events[0].error_detail == "too_large"


def test_requests_turned_away_early_are_counted(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    sample = fixture_bytes("tpt_v7_sample.xlsx")
    assert _post(client, "a.xlsx", sample, tpt_version="V9").status_code == 400
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    assert _post(client, "big.csv", b"x" * (3 * 1024 * 1024)).status_code == 413
    assert [(e.status, e.status_code) for e in events] == [("rejected", 400), ("rejected", 413)]
    bad_version, body_limit = events
    # In the handler: what is known about the upload is kept; the bad value itself is not.
    assert bad_version.error_detail == "bad_tpt_version" and bad_version.tpt_version is None
    assert (bad_version.direction, bad_version.source) == ("tpt-to-fundsxml", "sample")
    assert bad_version.input_bytes == len(sample)
    # Stopped by the body limit before the handler: nothing about the file.
    assert body_limit.direction is None and body_limit.source is None and body_limit.input_bytes is None


def test_handler_rejections_carry_direction_source_and_version(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    clean = fixture_bytes("01_clean.xlsx")
    assert _post(client, "e.xml", b"", tpt_version="V8").status_code == 400
    assert _post(client, "e", b"").status_code == 400
    nothing = {"include_block": "false", "include_core": "false"}
    assert _post(client, "a.xlsx", clean, tpt_version="v8", **nothing).status_code == 400
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    too_big = b"<FundsXML4/>" + b" " * (1024 * 1024)
    assert _post(client, "big.xml", too_big).status_code == 413
    assert [
        (e.status, e.status_code, e.error_detail, e.direction, e.source, e.tpt_version, e.input_bytes)
        for e in events
    ] == [
        ("rejected", 400, "empty_file", "fundsxml-to-tpt", "xml", "V8", 0),
        ("rejected", 400, "empty_file", None, None, None, 0),
        ("rejected", 400, "nothing_selected", "tpt-to-fundsxml", "xlsx", "V8", len(clean)),
        ("rejected", 413, "too_large", "fundsxml-to-tpt", "xml", None, 1024 * 1024 + 1),
    ]


def test_sample_and_mapping_events(client, events):
    client.get("/api/samples/tpt-v8")
    client.get("/api/samples/nope")
    client.get("/api/mapping/V7")
    client.get("/api/health")
    assert [(e.event_type, e.source, e.tpt_version) for e in events] == [
        ("sample_load", "tpt-v8", None),
        ("mapping_view", None, "V7"),
    ]


def test_disabled_tracker_emits_nothing(client, fixture_bytes):
    # The default tracker has no USAGE_DB_URL: requests work, nothing is recorded.
    assert not client.app.state.usage.enabled
    assert _post(client, "a.xlsx", fixture_bytes("tpt_v7_sample.xlsx")).status_code == 200


def test_page_view_only_for_known_routes(tmp_path, monkeypatch):
    from app import spa

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(spa, "emit", lambda event_type, **f: emitted.append((event_type, f)) or True)
    (tmp_path / "index.html").write_text("<title>x</title>", encoding="utf-8")
    mini = FastAPI()
    spa.mount_spa(mini, tmp_path)
    with TestClient(mini) as c:
        assert c.get("/mapping?utm_source=LinkedIn&utm_medium=bad value").status_code == 200
        assert c.get("/wp-login.php").status_code == 404
        assert c.get("/").status_code == 200
    assert emitted == [
        ("page_view", {"path": "/mapping", "status_code": 200, "status": "ok", "utm_source": "linkedin"}),
        ("page_view", {"path": "/", "status_code": 200, "status": "ok"}),
    ]


def test_channel_tells_the_spa_from_scripts(client, events, fixture_bytes):
    data = fixture_bytes("01_clean.xlsx")
    client.post("/api/convert", files={"file": ("a.xlsx", data)}, headers={"X-Client": "web"})
    _post(client, "a.xlsx", data, response="file")
    web, api = events
    assert (web.channel, web.response_mode) == ("web", "json")
    assert (api.channel, api.response_mode) == ("api", "file")


def test_formats_content_and_quality_are_recorded(client, events, fixture_bytes):
    _post(client, "a.xlsx", fixture_bytes("tpt_all_cic.xlsx"))
    (ev,) = events
    assert (ev.source_format, ev.target_format) == ("tpt", "fundsxml")
    assert {"1", "2", "3", "4", "7"} <= set(ev.cic_categories)
    assert ev.cic_categories == sorted(ev.cic_categories)
    assert ev.warning_count is not None and ev.info_count is not None
    assert ev.values_lost is not None and ev.values_kept_custom is not None
    assert ev.coverage_pct is not None and 0 < ev.coverage_pct <= 100
    assert ev.options == []


def test_openfunds_layout_templates_and_counts(client, events, fixture_bytes):
    _post(client, "of.xlsx", fixture_bytes("openfunds_sample.xlsx"), target="fundsxml")
    (ev,) = events
    assert (ev.source_format, ev.target_format) == ("openfunds", "fundsxml")
    assert ev.of_layout in ("flat", "narrow") and ev.shareclass_count and ev.holding_count
    assert set(ev.of_templates) <= {"EMT", "EPT", "EET", "EFT"}
    assert ev.cic_categories


def test_fundsxml_input_structure(client, events, fixture_bytes):
    _post(client, "f.xml", fixture_bytes("fundsxml_sample.xml"))
    (ev,) = events
    assert ev.source_format == "fundsxml" and ev.has_tpt_block in (True, False)
    assert ev.shareclass_count and ev.asset_count and ev.cic_categories


def test_non_default_options_are_named(client, events, fixture_bytes):
    data = fixture_bytes("openfunds_sample.xlsx")
    _post(client, "of.xlsx", data, target="fundsxml", implied_tpt_attributes="false", of_header_names="true")
    # of_header_names only applies to openfunds output
    assert events[0].options == ["no_implied_tpt_attributes"]


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "download", "target": "xlsx", "direction": "fundsxml-to-tpt"},
        {"type": "handoff", "target": "validator", "direction": "fundsxml-to-tpt", "outcome": "timeout"},
    ],
)
def test_download_and_handoff_events(client, events, payload):
    r = client.post("/api/usage/event", json=payload, headers={"X-Client": "web"})
    assert r.status_code == 204
    (ev,) = events
    assert ev.event_type == payload["type"] and ev.target == payload["target"]
    assert ev.status == payload.get("outcome", "ok") and ev.channel == "web"
    assert (ev.source_format, ev.target_format) == ("fundsxml", "tpt")


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "convert", "target": "xlsx"},
        {"type": "download", "target": "secret.xlsx"},
        {"type": "download", "target": "xlsx", "direction": "tpt-to-pdf"},
        {"type": "download", "target": "xlsx", "filename": "Fund A.xlsx"},
    ],
)
def test_usage_event_takes_fixed_values_only(client, events, payload):
    assert client.post("/api/usage/event", json=payload).status_code == 422
    assert events == []


def test_funds_are_counted_without_isin_or_date(client, events, fixture_bytes):
    data = fixture_bytes("tpt_v7_sample.xlsx")
    body = _post(client, "a.xlsx", data).json()
    _post(client, "b.xlsx", data)
    first, second = events
    isin = body["summary"]["portfolioList"][0]["id"]
    assert first.isin_countries == [isin[:2]]
    assert len(first.fund_keys) == 1 and first.fund_keys == second.fund_keys  # same fund, same key
    assert first.nav_months and all(len(m) == 7 for m in first.nav_months)
    assert isinstance(first.data_age_days, int)
    row = repr(dataclasses.astuple(first))
    assert isin not in row
    for p in body["summary"]["portfolioList"]:
        assert p["date"] not in row


def test_fund_keys_need_the_secret():
    from datetime import date

    from app.usage.conversion import fund_fields

    with_secret = fund_fields(["LU0000000001", "bad"], ["2026-09-30"], "s", date(2026, 10, 23))
    assert with_secret["isin_countries"] == ["LU"] and with_secret["nav_months"] == ["2026-09"]
    assert with_secret["data_age_days"] == 23 and len(with_secret["fund_keys"]) == 1
    other = fund_fields(["LU0000000001"], [], "other", date(2026, 10, 23))
    assert other["fund_keys"] != with_secret["fund_keys"]
    assert "fund_keys" not in fund_fields(["LU0000000001"], [], None, date(2026, 10, 23))
