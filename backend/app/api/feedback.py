"""POST /api/feedback – same contract as the XSD/XML/OData viewers' feedback endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import release_version
from app.rate_limit import client_ip, limiter
from app.usage.context import current, utc_today
from app.usage.events import classify_device, truncate, visitor_hash
from app.usage.feedback import FeedbackRow, FeedbackStore

logger = logging.getLogger(__name__)
router = APIRouter()

FEEDBACK_LIMIT = "5/minute"
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class FeedbackPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL_PATTERN)
    page: str | None = Field(default=None, max_length=255)
    direction: str | None = Field(default=None, max_length=32)
    tpt_version: str | None = Field(default=None, max_length=8)
    error_detail: str | None = Field(default=None, max_length=255)
    # Honeypot: real users never see this field; bots that fill it are dropped silently.
    website: str | None = Field(default=None, max_length=255)


@router.post("/feedback", status_code=204)
@limiter.limit(FEEDBACK_LIMIT)
async def submit_feedback(request: Request, payload: FeedbackPayload) -> Response:
    message = payload.message.strip()
    if not message:
        raise HTTPException(422, "message must not be empty")
    if payload.website:
        return Response(status_code=204)

    # Same pseudonymisation as usage events: the tracker (if any) supplies the
    # daily-salted visitor hash and GeoIP country; the raw IP is never stored.
    ctx = current()
    ua = ctx.user_agent if ctx else request.headers.get("user-agent")
    ip = ctx.ip if ctx else client_ip(request)
    tracker = ctx.tracker if ctx else None
    row = FeedbackRow(
        message=message,
        email=(payload.email or "").strip() or None,
        page=truncate(payload.page),
        direction=truncate(payload.direction),
        tpt_version=truncate(payload.tpt_version),
        error_detail=truncate(payload.error_detail),
        visitor_hash=visitor_hash(ip, ua, utc_today(), tracker.hash_secret) if tracker else None,
        country_code=tracker.geoip.country(ip) if tracker and tracker.geoip else None,
        user_agent=truncate(ua),
        device=classify_device(ua),
        app_version=release_version(),
    )

    store: FeedbackStore | None = getattr(request.app.state, "feedback", None)
    if store is not None and store.enabled:
        try:
            await store.save(row)
        except Exception as exc:  # noqa: BLE001 - report honestly, never 500
            logger.warning("feedback insert failed: %r", exc)
            raise HTTPException(503, "could not store feedback, please try again later") from exc
        logger.info("feedback stored (page %s)", row.page)
    else:
        # No database configured: keep the feedback in the log.
        logger.warning(
            "user feedback (no USAGE_DB_URL configured): page=%s direction=%s version=%s "
            "error=%s email=%s message=%r",
            row.page,
            row.direction,
            row.tpt_version,
            row.error_detail,
            row.email,
            row.message,
        )
    return Response(status_code=204)
