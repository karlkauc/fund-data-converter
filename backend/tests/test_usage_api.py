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


def test_sample_upload_is_marked(client, events, fixture_bytes):
    _post(client, "tpt_v7_sample.xlsx", fixture_bytes("tpt_v7_sample.xlsx"))
    assert events[0].source == "sample"


def test_parse_error_keeps_only_the_exception_class(client, events):
    assert _post(client, "x.xml", b"<foo>Secret Fund</foo>").status_code == 422
    (ev,) = events
    assert ev.status == "parse_error" and ev.status_code == 422
    assert ev.error_detail == "FundsXmlReadError" and ev.direction == "fundsxml-to-tpt"
    assert "Secret" not in repr(dataclasses.astuple(ev))


def test_too_many_positions_is_rejected(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_positions", 1)
    assert _post(client, "a.xlsx", fixture_bytes("tpt_v7_sample.xlsx")).status_code == 422
    assert events[0].status == "rejected" and events[0].error_detail == "TooLargeError"


def test_requests_turned_away_early_are_counted(client, events, fixture_bytes, monkeypatch):
    from app.config import settings

    assert _post(client, "a.xlsx", fixture_bytes("tpt_v7_sample.xlsx"), tpt_version="V9").status_code == 400
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    assert _post(client, "big.csv", b"x" * (3 * 1024 * 1024)).status_code == 413
    assert [(e.status, e.status_code) for e in events] == [("rejected", 400), ("rejected", 413)]


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
