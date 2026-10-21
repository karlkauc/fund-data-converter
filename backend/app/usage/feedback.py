"""Persist user feedback (POST /api/feedback) in the usage-stats Postgres.

Rows go to the ``feedback`` table (see backend/sql/feedback.sql) when a DSN is
configured. Without one the store is *inert* and the API falls back to
writing the feedback into the application log, so local dev, tests and an
unconfigured deployment still accept feedback instead of failing.

Unlike usage events, feedback is written synchronously inside the request:
it is rare, and the user deserves an honest "sent" / "failed".
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, fields
from typing import Any

from app.usage.recorder import ConnectFn, _default_connect

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeedbackRow:
    """One row of the ``feedback`` table (column order = field order)."""

    message: str
    email: str | None = None
    page: str | None = None
    direction: str | None = None
    tpt_version: str | None = None
    error_detail: str | None = None
    visitor_hash: str | None = None
    country_code: str | None = None
    user_agent: str | None = None
    device: str | None = None
    app_version: str | None = None

    def as_row(self) -> tuple:
        return tuple(getattr(self, f.name) for f in fields(self))


FEEDBACK_COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(FeedbackRow))
FEEDBACK_INSERT_SQL = (
    f"INSERT INTO feedback ({', '.join(FEEDBACK_COLUMNS)}) "
    f"VALUES ({', '.join('%s' for _ in FEEDBACK_COLUMNS)})"
)


class FeedbackStore:
    def __init__(
        self,
        dsn: str,
        password: str = "",
        *,
        connect: ConnectFn = _default_connect,
        connect_timeout: int = 5,
    ) -> None:
        self._dsn = dsn.strip()
        # Secret-manager values often carry a trailing newline; never let that break auth.
        self._password = password.strip("\r\n")
        self._connect = connect
        self._connect_timeout = connect_timeout

    @property
    def enabled(self) -> bool:
        return bool(self._dsn)

    async def save(self, row: FeedbackRow) -> None:
        """Insert one row on a fresh connection. Raises on failure."""
        kwargs: dict[str, Any] = {"connect_timeout": self._connect_timeout, "autocommit": False}
        if self._password:
            kwargs["password"] = self._password
        conn = await self._connect(self._dsn, **kwargs)
        try:
            async with conn.cursor() as cur:
                await cur.execute(FEEDBACK_INSERT_SQL, row.as_row())
            await conn.commit()
        finally:
            with contextlib.suppress(Exception):
                await conn.close()
