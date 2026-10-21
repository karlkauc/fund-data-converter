from __future__ import annotations

import pytest

from app.usage.feedback import FEEDBACK_COLUMNS, FEEDBACK_INSERT_SQL, FeedbackRow, FeedbackStore


class ListStore(FeedbackStore):
    def __init__(self, fail: bool = False) -> None:
        super().__init__("postgresql://fake")
        self.rows: list[FeedbackRow] = []
        self.fail = fail

    async def save(self, row: FeedbackRow) -> None:
        if self.fail:
            raise OSError("db down")
        self.rows.append(row)


@pytest.fixture
def store(client) -> ListStore:
    s = ListStore()
    client.app.state.feedback = s
    return s


def test_feedback_is_stored(client, store):
    r = client.post(
        "/api/feedback",
        json={
            "message": "  Field 12 is wrong  ",
            "email": "a@b.example",
            "page": "/",
            "direction": "tpt-to-fundsxml",
            "tpt_version": "V7",
            "error_detail": "Conversion failed",
        },
        headers={"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"},
    )
    assert r.status_code == 204
    (row,) = store.rows
    assert row.message == "Field 12 is wrong" and row.email == "a@b.example"
    assert row.direction == "tpt-to-fundsxml" and row.tpt_version == "V7"
    assert row.device == "desktop" and row.app_version


def test_feedback_validation(client, store):
    assert client.post("/api/feedback", json={"message": ""}).status_code == 422
    assert client.post("/api/feedback", json={"message": "   "}).status_code == 422
    assert client.post("/api/feedback", json={"message": "x", "email": "nope"}).status_code == 422
    assert client.post("/api/feedback", json={"message": "x" * 4001}).status_code == 422
    assert store.rows == []


def test_honeypot_is_dropped_silently(client, store):
    assert client.post("/api/feedback", json={"message": "buy", "website": "spam"}).status_code == 204
    assert store.rows == []


def test_db_failure_is_reported(client):
    client.app.state.feedback = ListStore(fail=True)
    assert client.post("/api/feedback", json={"message": "hi"}).status_code == 503


def test_without_db_feedback_goes_to_the_log(client, caplog):
    assert not client.app.state.feedback.enabled
    with caplog.at_level("WARNING"):
        assert client.post("/api/feedback", json={"message": "hello there"}).status_code == 204
    assert "hello there" in caplog.text


def test_rate_limited(client, store):
    codes = [client.post("/api/feedback", json={"message": "x"}).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_insert_sql_matches_row():
    assert FEEDBACK_INSERT_SQL.count("%s") == len(FEEDBACK_COLUMNS) == len(FeedbackRow("m").as_row())
