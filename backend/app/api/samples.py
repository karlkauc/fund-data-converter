"""GET /api/samples/{name} – bundled example files for "Try an example" (built by tools/make_samples.py)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.usage.context import emit

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XML = "application/xml"
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples"
# Keep in sync with SAMPLE_FILES in frontend/src/lib/api.ts.
SAMPLES = {
    "tpt-v7": ("tpt_v7_sample.xlsx", XLSX),
    "tpt-v8": ("tpt_v8_sample.xlsx", XLSX),
    "tpt-all-cic": ("tpt_all_cic.xlsx", XLSX),
    "tpt-multi": ("tpt_multi_fund.xlsx", XLSX),
    "tpt-csv": ("tpt_semicolon.csv", "text/csv"),
    "tpt-errors": ("tpt_with_errors.xlsx", XLSX),
    "fundsxml": ("fundsxml_sample.xml", XML),
    "fundsxml-all-cic": ("fundsxml_all_cic.xml", XML),
    "fundsxml-core-only": ("fundsxml_core_only.xml", XML),
    "fundsxml-fund-portfolio": ("fundsxml_fund_portfolio.xml", XML),
    "fundsxml-openfunds": ("fundsxml_from_openfunds.xml", XML),
    "fundsxml-errors": ("fundsxml_with_errors.xml", XML),
    "openfunds": ("openfunds_sample.xlsx", XLSX),
    "openfunds-multi": ("openfunds_multi.xlsx", XLSX),
    "openfunds-static": ("openfunds_static.xlsx", XLSX),
    "openfunds-zip": ("openfunds_csv.zip", "application/zip"),
    "openfunds-errors": ("openfunds_with_errors.xlsx", XLSX),
}


@router.get("/samples/{name}")
async def sample(name: str, download: bool = False) -> FileResponse:
    """The example file; ``download=1`` marks a download link (saved, not loaded into the converter)."""
    entry = SAMPLES.get(name)
    if entry is None:
        raise HTTPException(404, "unknown sample")
    filename, mime = entry
    # A download is a sample_load too (the event types are fixed in the stats DB), told apart by its source.
    emit("sample_load", source=f"{name}:download" if download else name, status_code=200, status="ok")
    return FileResponse(
        SAMPLE_DIR / filename,
        media_type=mime,
        filename=filename,
        headers={"Cache-Control": "public, max-age=86400"},
    )
