"""Article CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.schemas import ArticleCreate, ArticleUpdate
from app.api.serializers import article_payload, topic_payload
from app.article_generation.topic_selection.service import TopicService
from app.core.constants import ArticleStatus, DEFAULT_PLATFORMS
from app.core.errors import NotFoundError
from app.models.article import Article, Topic

router = APIRouter(prefix="/articles", tags=["articles"])


def get_article(session: Session, article_id: str) -> Article:
    article = session.get(Article, article_id)
    if article is None:
        raise NotFoundError(f"文章不存在: {article_id}")
    return article


@router.get("")
def list_articles(
    session: Session = SessionDep,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    query = select(Article)
    count_query = select(func.count(Article.id))
    if status:
        query = query.where(Article.status == status)
        count_query = count_query.where(Article.status == status)
    total = session.scalar(count_query) or 0
    articles = list(
        session.scalars(
            query.order_by(Article.updated_at.desc()).limit(limit).offset(offset)
        )
    )
    return {"items": [article_payload(item) for item in articles], "total": total}


@router.post("", status_code=201)
def create_article(payload: ArticleCreate, session: Session = SessionDep) -> dict:
    article = Article(
        title=payload.title.strip(),
        topic_mode=payload.topic_mode,
        target_platforms=payload.target_platforms or list(DEFAULT_PLATFORMS),
        publish_confirmation=(
            True if payload.publish_confirmation is None else payload.publish_confirmation
        ),
        status=ArticleStatus.DRAFT,
    )
    session.add(article)
    session.commit()
    if payload.topic_mode == "manual" and payload.title.strip():
        service = TopicService(session, llm=None)  # type: ignore[arg-type]
        topic = service.create_manual(
            article.id,
            title=payload.title.strip(),
            angle=payload.angle,
            target_platforms=list(article.target_platforms or []),
        )
        service.select(article.id, topic.id)
    session.refresh(article)
    return {"article": article_payload(article), "topics": _topics(session, article.id)}


@router.get("/{article_id}")
def get_article_detail(article_id: str, session: Session = SessionDep) -> dict:
    article = get_article(session, article_id)
    return {"article": article_payload(article), "topics": _topics(session, article.id)}


@router.patch("/{article_id}")
def update_article(
    article_id: str, payload: ArticleUpdate, session: Session = SessionDep
) -> dict:
    article = get_article(session, article_id)
    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(article, key, value)
    session.commit()
    session.refresh(article)
    return article_payload(article)


@router.delete("/{article_id}", status_code=204)
def delete_article(article_id: str, session: Session = SessionDep) -> None:
    article = get_article(session, article_id)
    session.delete(article)
    session.commit()


def _topics(session: Session, article_id: str) -> list[dict]:
    topics = list(
        session.scalars(
            select(Topic).where(Topic.article_id == article_id).order_by(Topic.created_at)
        )
    )
    return [topic_payload(topic) for topic in topics]
