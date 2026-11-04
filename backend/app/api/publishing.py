"""Formatting, publishing and manual fallback endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.articles import get_article
from app.api.deps import LLMDep, PlatformsDep, SessionDep
from app.api.schemas import ManualPublish, PublishRequest
from app.api.serializers import (
    format_payload,
    history_payload,
    publish_payload,
)
from app.article_generation.formatting.service import FormattingService
from app.article_generation.publishing.service import PublishingService
from app.core.errors import ConflictError, NotFoundError
from app.core.security import CredentialService
from app.models.article import PublishRecord, PublishStatusHistory

router = APIRouter(prefix="/articles/{article_id}", tags=["publishing"])


@router.get("/formats")
def list_formats(
    article_id: str, session: Session = SessionDep, platforms=PlatformsDep
) -> dict:
    get_article(session, article_id)
    service = FormattingService(session, platforms, CredentialService(session))
    return {"items": [format_payload(item) for item in service.list_outputs(article_id)]}


@router.post("/formats")
def format_article(
    article_id: str,
    payload: PublishRequest,
    session: Session = SessionDep,
    platforms=PlatformsDep,
    llm=LLMDep,
) -> dict:
    get_article(session, article_id)
    service = FormattingService(session, platforms, CredentialService(session), llm=llm)
    result = service.format_article(article_id, payload.platforms)
    return {
        "items": [format_payload(item) for item in result.outputs],
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.post("/formats/{platform}/retry")
def retry_format(
    article_id: str,
    platform: str,
    session: Session = SessionDep,
    platforms=PlatformsDep,
    llm=LLMDep,
) -> dict:
    get_article(session, article_id)
    service = FormattingService(session, platforms, CredentialService(session), llm=llm)
    return format_payload(service.retry(article_id, platform))


@router.get("/publish/records")
def list_publish_records(article_id: str, session: Session = SessionDep) -> dict:
    get_article(session, article_id)
    records = list(
        session.scalars(
            select(PublishRecord)
            .where(PublishRecord.article_id == article_id)
            .order_by(PublishRecord.platform)
        )
    )
    return {"items": [publish_payload(item) for item in records]}


@router.get("/confirm-summary")
def confirm_summary(
    article_id: str, session: Session = SessionDep, platforms=PlatformsDep
) -> dict:
    get_article(session, article_id)
    service = PublishingService(session, platforms, CredentialService(session))
    return service.confirm_summary(article_id)


@router.post("/publish")
def publish_now(
    article_id: str,
    payload: PublishRequest,
    session: Session = SessionDep,
    platforms=PlatformsDep,
) -> dict:
    get_article(session, article_id)
    service = PublishingService(session, platforms, CredentialService(session))
    result = service.publish(article_id, payload.platforms)
    return {
        "items": [publish_payload(item) for item in result.records],
        "errors": result.errors,
        "skipped": result.skipped,
    }


@router.post("/publish/{platform}/retry")
def retry_publish(
    article_id: str,
    platform: str,
    session: Session = SessionDep,
    platforms=PlatformsDep,
) -> dict:
    get_article(session, article_id)
    record = session.scalar(
        select(PublishRecord).where(
            PublishRecord.article_id == article_id, PublishRecord.platform == platform
        )
    )
    if record is None:
        raise NotFoundError("发布记录不存在")
    if record.status == "published":
        raise ConflictError("该平台已发布，无需重试")
    service = PublishingService(session, platforms, CredentialService(session))
    result = service.publish(article_id, [platform])
    return {
        "items": [publish_payload(item) for item in result.records],
        "errors": result.errors,
    }


@router.post("/publish/{platform}/manual")
def manual_publish(
    article_id: str,
    platform: str,
    payload: ManualPublish,
    session: Session = SessionDep,
    platforms=PlatformsDep,
) -> dict:
    get_article(session, article_id)
    service = PublishingService(session, platforms, CredentialService(session))
    record = service.manual_backfill(
        article_id,
        platform=platform,
        url=payload.url,
        remote_id=payload.remote_id,
        status=payload.status,
    )
    return publish_payload(record)


@router.get("/publish/{platform}/history")
def publish_history(
    article_id: str, platform: str, session: Session = SessionDep, platforms=PlatformsDep
) -> dict:
    get_article(session, article_id)
    service = PublishingService(session, platforms, CredentialService(session))
    rows = service.history(article_id, platform)
    return {"items": [history_payload(item) for item in rows]}


@router.get("/publish/history")
def all_publish_history(article_id: str, session: Session = SessionDep) -> dict:
    get_article(session, article_id)
    rows = list(
        session.scalars(
            select(PublishStatusHistory)
            .join(PublishRecord, PublishRecord.id == PublishStatusHistory.publish_record_id)
            .where(PublishRecord.article_id == article_id)
            .order_by(PublishStatusHistory.created_at)
        )
    )
    return {
        "items": [
            {
                **history_payload(item),
                "platform": _platform_for(session, item.publish_record_id),
            }
            for item in rows
        ]
    }


def _platform_for(session: Session, record_id: str) -> str | None:
    record = session.get(PublishRecord, record_id)
    return record.platform if record else None
