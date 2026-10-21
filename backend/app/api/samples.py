"""GET /api/samples/{name} – bundled example files for "Try an example"."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.usage.context import emit

router = APIRouter()

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLES = {
    "tpt-v7": ("tpt_v7_sample.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "tpt-v8": ("tpt_v8_sample.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "fundsxml": ("fundsxml_sample.xml", "application/xml"),
}


@router.get("/samples/{name}")
async def sample(name: str) -> FileResponse:
    entry = SAMPLES.get(name)
    if entry is None:
        raise HTTPException(404, "unknown sample")
    filename, mime = entry
    emit("sample_load", source=name, status_code=200, status="ok")
    return FileResponse(
        SAMPLE_DIR / filename,
        media_type=mime,
        filename=filename,
        headers={"Cache-Control": "public, max-age=86400"},
    )
