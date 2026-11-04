"""Operational analytics and metric collection endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import PlatformsDep, SessionDep
from app.api.schemas import ManualMetrics
from app.api.serializers import metric_payload
from app.analytics.collector import MetricsCollector
from app.analytics.service import AnalyticsService
from app.core.errors import NotFoundError
from app.core.security import CredentialService
from app.models.article import Article
from app.models.llm import LLMCall

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def summary(
    session: Session = SessionDep,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> dict:
    return AnalyticsService(session).summary(date_from=date_from, date_to=date_to)


@router.get("/performance")
def performance(
    session: Session = SessionDep,
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> dict:
    rows = AnalyticsService(session).performance_rows(
        date_from=date_from, date_to=date_to
    )
    return {"items": rows}


@router.get("/articles/{article_id}")
def article_performance(article_id: str, session: Session = SessionDep) -> dict:
    service = AnalyticsService(session)
    if session.get(Article, article_id) is None:
        raise NotFoundError(f"文章不存在: {article_id}")
    return service.article_performance(article_id)


@router.get("/costs")
def cost_summary(
    session: Session = SessionDep,
    article_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> dict:
    if article_id:
        return AnalyticsService(session).article_cost(article_id)
    query = select(
        LLMCall.stage,
        LLMCall.model,
        func.count(LLMCall.id),
        func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
        func.coalesce(func.sum(LLMCall.completion_tokens), 0),
        func.sum(LLMCall.cost),
        func.sum(LLMCall.estimated),
        func.sum(LLMCall.price_missing),
    ).group_by(LLMCall.stage, LLMCall.model)
    if date_from is not None:
        query = query.where(LLMCall.created_at >= date_from)
    if date_to is not None:
        query = query.where(LLMCall.created_at <= date_to)
    rows = []
    for stage, model, calls, prompt, completion, cost, estimated, missing in session.execute(query).all():
        rows.append(
            {
                "stage": stage,
                "model": model,
                "calls": int(calls or 0),
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "cost": None if cost is None else round(float(cost), 6),
                "estimated_calls": int(estimated or 0),
                "price_missing_calls": int(missing or 0),
            }
        )
    return {"items": rows}


@router.post("/collect")
def collect_metrics(
    session: Session = SessionDep,
    platforms=PlatformsDep,
    article_id: str | None = Query(default=None),
) -> dict:
    collector = MetricsCollector(session, platforms, CredentialService(session))
    result = collector.collect(article_id)
    return {
        "items": [metric_payload(item) for item in result.snapshots],
        "skipped": result.skipped,
        "errors": result.errors,
    }


@router.post("/records/{record_id}/metrics", status_code=201)
def manual_metrics(
    record_id: str, payload: ManualMetrics, session: Session = SessionDep, platforms=PlatformsDep
) -> dict:
    collector = MetricsCollector(session, platforms, CredentialService(session))
    snapshot = collector.add_manual(
        record_id,
        views=payload.views,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        revenue_cents=payload.revenue_cents,
    )
    return metric_payload(snapshot)
