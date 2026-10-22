from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("STATIC_DIR", "/nonexistent")

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLES = Path(__file__).parent.parent / "app" / "samples"


@pytest.fixture
def fixture_bytes():
    def load(name: str) -> bytes:
        path = FIXTURES / name
        if not path.exists():
            path = SAMPLES / name
        return path.read_bytes()

    return load


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.rate_limit import convert_quota, limiter

    limiter.reset()
    convert_quota.reset()
    with TestClient(app) as c:
        yield c
