"""Client for findatex-validator's web API (``POST /api/validate``), shared by the batch tools."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv"


class ValidatorError(Exception):
    pass


def post(client: httpx.Client, url: str, path: Path, version: str, profiles: list[str]) -> dict:
    """The validator's response body for one TPT file; raises ``ValidatorError`` when it fails."""
    data = {
        "templateId": "TPT",
        "templateVersion": f"{version}.0",
        "externalEnabled": "false",
        "profiles": profiles,
    }
    media = CSV if path.suffix.lower() == ".csv" else XLSX
    error = "no attempt"
    # Generous retries: a crashed validator needs a while to come back.
    for attempt in range(8):
        try:
            with path.open("rb") as fh:
                r = client.post(f"{url}/api/validate", data=data, files={"file": (path.name, fh, media)})
        except httpx.HTTPError as exc:
            error = f"{type(exc).__name__}: {exc}"
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (429, 503):
            error = f"HTTP {r.status_code}"
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise ValidatorError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
    raise ValidatorError(error)
