"""Content the SPA shares with the server-rendered pages, so it has one source."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.content.pages import home_faq
from app.content.render import markdown

router = APIRouter(tags=["content"])


class FaqEntry(BaseModel):
    question: str
    answer_html: str


@router.get("/content/faq", response_model=list[FaqEntry])
async def faq(response: Response) -> list[FaqEntry]:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return [FaqEntry(question=item.question, answer_html=markdown(item.answer)) for item in home_faq()]
