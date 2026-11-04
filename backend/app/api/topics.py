"""Topic recommendation and selection endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.articles import get_article
from app.api.deps import LLMDep, SessionDep, SkillsDep
from app.api.schemas import RecommendRequest, TopicCreate, TopicUpdate
from app.api.serializers import article_payload, topic_payload
from app.article_generation.topic_selection.service import TopicService
from app.core.errors import NotFoundError
from app.models.article import Article, Topic
from app.skills.manager import SkillManager

router = APIRouter(tags=["topics"])


@router.get("/articles/{article_id}/topics")
def list_topics(article_id: str, session: Session = SessionDep) -> dict:
    get_article(session, article_id)
    topics = TopicService(session, llm=None).list_topics(article_id)  # type: ignore[arg-type]
    return {"items": [topic_payload(item) for item in topics]}


@router.post("/articles/{article_id}/topics", status_code=201)
def create_topic(
    article_id: str, payload: TopicCreate, session: Session = SessionDep
) -> dict:
    service = TopicService(session, llm=None)  # type: ignore[arg-type]
    topic = service.create_manual(
        article_id,
        title=payload.title,
        angle=payload.angle,
        target_platforms=payload.target_platforms,
        rationale=payload.rationale,
        content_format=payload.content_format,
    )
    return topic_payload(topic)


@router.post("/articles/{article_id}/topics/recommend")
def recommend_topics(
    article_id: str,
    payload: RecommendRequest,
    session: Session = SessionDep,
    llm=LLMDep,
    registry=SkillsDep,
) -> dict:
    get_article(session, article_id)
    service = TopicService(
        session, llm, skills=SkillManager(session, registry)
    )
    result = service.recommend(
        article_id, domain=payload.domain, exclude_titles=payload.exclude_titles
    )
    return {
        "items": [topic_payload(item) for item in result.topics],
        "fallback_used": result.fallback_used,
        "hot_signal_count": result.hot_signal_count,
        "hot_errors": result.hot_errors,
    }


@router.post("/articles/{article_id}/topics/{topic_id}/select")
def select_topic(article_id: str, topic_id: str, session: Session = SessionDep) -> dict:
    service = TopicService(session, llm=None)  # type: ignore[arg-type]
    selection = service.select(article_id, topic_id)
    article = get_article(session, article_id)
    return {
        "topic": topic_payload(selection.topic),
        "article": article_payload(article),
        "source_fetch": selection.source_fetch.as_dict(),
    }


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: str, payload: TopicUpdate, session: Session = SessionDep) -> dict:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("选题不存在")
    service = TopicService(session, llm=None)  # type: ignore[arg-type]
    fields = payload.model_dump(exclude_unset=True)
    updated = service.update_topic(topic.article_id, topic_id, **fields)
    return topic_payload(updated)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: str, session: Session = SessionDep) -> None:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("选题不存在")
    article = session.get(Article, topic.article_id)
    if article is not None and article.current_topic_id == topic.id:
        article.current_topic_id = None
    session.delete(topic)
    session.commit()


@router.post("/topics/{topic_id}/select")
def select_topic_short(topic_id: str, session: Session = SessionDep) -> dict:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("选题不存在")
    service = TopicService(session, llm=None)  # type: ignore[arg-type]
    selection = service.select(topic.article_id, topic.id)
    article = get_article(session, topic.article_id)
    return {
        "topic": topic_payload(selection.topic),
        "article": article_payload(article),
        "source_fetch": selection.source_fetch.as_dict(),
    }


@router.get("/topics/{topic_id}")
def get_topic(topic_id: str, session: Session = SessionDep) -> dict:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise NotFoundError("选题不存在")
    return topic_payload(topic)


def topics_for_article(session: Session, article_id: str) -> list[Topic]:
    return list(session.scalars(select(Topic).where(Topic.article_id == article_id)))
