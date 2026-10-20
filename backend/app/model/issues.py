"""User-facing conversion messages."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Issue:
    level: str  # "error", "warning", "info"
    code: str
    message: str
    field: str | None = None  # TPT numKey
    row: int | None = None  # 1-based source row (TPT) or position index
    path: str | None = None  # FundsXML path
    value: str | None = None
    detail: str | None = None  # technical reason (schema wording), not translated
    params: dict | None = None  # values for the frontend's translated message templates

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
