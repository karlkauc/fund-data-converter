"""POST /api/usage/event – what the browser does with a result: download it, hand it over.

The server cannot see either: the download is a blob link, the hand-over a postMessage between
tabs. The SPA reports them with fixed values only (no file, no name), so the statistics can
follow a conversion through to its use. Anything else is refused.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from app.rate_limit import limiter
from app.service import DIRECTIONS
from app.usage.context import emit

router = APIRouter()

USAGE_EVENT_LIMIT = "60/minute"
Direction = Literal[DIRECTIONS]  # type: ignore[valid-type]


class UsageEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["download", "handoff"]
    target: Literal["xml", "xlsx", "csv", "zip", "validator", "xml-viewer"]
    direction: Direction | None = None
    # handoff: ok (posted) | timeout (the other tab never answered) | blocked (no popup)
    outcome: Literal["ok", "timeout", "blocked"] = "ok"


@router.post("/usage/event", status_code=204, include_in_schema=False)
@limiter.limit(USAGE_EVENT_LIMIT)
async def usage_event(request: Request, payload: UsageEventPayload) -> Response:
    source, _, target = (payload.direction or "").partition("-to-")
    emit(
        payload.type,
        status=payload.outcome,
        target=payload.target,
        direction=payload.direction,
        source_format=source or None,
        target_format=target or None,
    )
    return Response(status_code=204)
