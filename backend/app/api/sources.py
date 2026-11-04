"""Manual research source endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.schemas import SourceCreate
from app.api.serializers import source_payload
from app.article_generation.research.service import ResearchService

router = APIRouter(prefix="/articles/{article_id}/sources", tags=["sources"])


def _service(session: Session) -> ResearchService:
    return ResearchService(session, llm=None)  # type: ignore[arg-type]


@router.get("")
def list_sources(article_id: str, session: Session = SessionDep) -> dict:
    service = _service(session)
    service._article(article_id)
    return {"items": [source_payload(item) for item in service.list_sources(article_id)]}


@router.post("", status_code=201)
def add_source(article_id: str, payload: SourceCreate, session: Session = SessionDep) -> dict:
    source = _service(session).add_source(
        article_id,
        title=payload.title,
        url=payload.url,
        snippet=payload.snippet,
    )
    return source_payload(source)


@router.delete("/{source_id}", status_code=204)
def remove_source(article_id: str, source_id: str, session: Session = SessionDep) -> None:
    _service(session).remove_source(article_id, source_id)
