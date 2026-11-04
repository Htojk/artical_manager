"""Aggregated analytics for articles, costs and publication performance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.article import Article, MetricSnapshot, PublishRecord, ReviewReport
from app.models.llm import LLMCall as CallModel


class AnalyticsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def article_cost(self, article_id: str) -> dict:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        rows = self.session.execute(
            select(
                CallModel.stage,
                CallModel.model,
                func.count(CallModel.id),
                func.coalesce(func.sum(CallModel.prompt_tokens), 0),
                func.coalesce(func.sum(CallModel.completion_tokens), 0),
                func.sum(CallModel.cost),
                func.sum(CallModel.estimated),
                func.sum(CallModel.price_missing),
            )
            .where(CallModel.article_id == article_id)
            .group_by(CallModel.stage, CallModel.model)
        ).all()
        stages: dict[str, dict] = {}
        total_cost = 0.0
        for stage, model, calls, prompt, completion, cost, estimated, price_missing in rows:
            stage_entry = stages.setdefault(
                stage,
                {
                    "stage": stage,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost": 0.0,
                    "calls": 0,
                    "estimated_calls": 0,
                    "price_missing_calls": 0,
                    "models": [],
                },
            )
            stage_entry["prompt_tokens"] += int(prompt or 0)
            stage_entry["completion_tokens"] += int(completion or 0)
            stage_entry["calls"] += int(calls or 0)
            stage_entry["cost"] += float(cost or 0.0)
            stage_entry["estimated_calls"] += int(estimated or 0)
            stage_entry["price_missing_calls"] += int(price_missing or 0)
            stage_entry["models"].append(
                {
                    "model": model,
                    "calls": int(calls or 0),
                    "prompt_tokens": int(prompt or 0),
                    "completion_tokens": int(completion or 0),
                    "cost": None if cost is None else round(float(cost), 6),
                }
            )
            total_cost += float(cost or 0.0)
        latest = self._latest_metrics(article_id=article_id)
        return {
            "article_id": article_id,
            "title": article.title,
            "total_cost": round(total_cost, 6),
            "by_stage": sorted(stages.values(), key=lambda item: item["stage"]),
            "metrics": latest,
        }

    def _latest_metrics(self, *, article_id: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None) -> dict:
        query = select(PublishRecord)
        if article_id:
            query = query.where(PublishRecord.article_id == article_id)
        records = list(self.session.scalars(query))
        views = likes = comments = shares = revenue = 0
        by_platform: dict[str, dict] = {}
        for record in records:
            snapshot_query = select(MetricSnapshot).where(
                MetricSnapshot.publish_record_id == record.id
            )
            if date_from is not None:
                snapshot_query = snapshot_query.where(MetricSnapshot.captured_at >= date_from)
            if date_to is not None:
                snapshot_query = snapshot_query.where(MetricSnapshot.captured_at <= date_to)
            snapshot = self.session.scalar(
                snapshot_query.order_by(MetricSnapshot.captured_at.desc())
            )
            if snapshot is None:
                continue
            views += snapshot.views
            likes += snapshot.likes
            comments += snapshot.comments
            shares += snapshot.shares
            revenue += snapshot.revenue_cents
            by_platform[record.platform] = {
                "views": snapshot.views,
                "likes": snapshot.likes,
                "comments": snapshot.comments,
                "shares": snapshot.shares,
                "revenue_cents": snapshot.revenue_cents,
                "captured_at": snapshot.captured_at.isoformat(),
            }
        return {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "revenue_cents": revenue,
            "revenue_yuan": round(revenue / 100.0, 2),
            "by_platform": by_platform,
        }

    def article_performance(self, article_id: str) -> dict:
        cost = self.article_cost(article_id)
        revenue = cost["metrics"]["revenue_yuan"]
        total_cost = cost["total_cost"]
        cost["roi"] = None if total_cost == 0 else round(revenue / total_cost, 3)
        latest_review = self.session.scalar(
            select(ReviewReport)
            .where(ReviewReport.article_id == article_id)
            .order_by(ReviewReport.created_at.desc())
        )
        cost["latest_review"] = (
            {
                "total": latest_review.total,
                "verdict": latest_review.verdict,
                "rollback_to": latest_review.rollback_to,
            }
            if latest_review
            else None
        )
        return cost

    def summary(self, *, date_from: datetime | None = None, date_to: datetime | None = None) -> dict:
        articles = list(self.session.scalars(select(Article)))
        published = [item for item in articles if item.status == "published"]
        cost_query = select(func.coalesce(func.sum(CallModel.cost), 0.0), func.coalesce(func.sum(CallModel.prompt_tokens), 0), func.coalesce(func.sum(CallModel.completion_tokens), 0))
        if date_from is not None:
            cost_query = cost_query.where(CallModel.created_at >= date_from)
        if date_to is not None:
            cost_query = cost_query.where(CallModel.created_at <= date_to)
        total_cost, prompt_tokens, completion_tokens = self.session.execute(cost_query).one()
        metrics = self._latest_metrics(date_from=date_from, date_to=date_to)
        return {
            "articles": len(articles),
            "published_articles": len(published),
            "total_cost": round(float(total_cost or 0.0), 6),
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "metrics": metrics,
            "revenue_yuan": metrics["revenue_yuan"],
            "roi": None
            if not total_cost
            else round(metrics["revenue_yuan"] / float(total_cost), 3),
        }

    def performance_rows(self, *, date_from: datetime | None = None, date_to: datetime | None = None) -> list[dict]:
        rows: list[dict] = []
        for article in self.session.scalars(select(Article).order_by(Article.updated_at.desc())):
            cost_query = select(func.coalesce(func.sum(CallModel.cost), 0.0)).where(
                CallModel.article_id == article.id
            )
            if date_from is not None:
                cost_query = cost_query.where(CallModel.created_at >= date_from)
            if date_to is not None:
                cost_query = cost_query.where(CallModel.created_at <= date_to)
            cost = float(self.session.scalar(cost_query) or 0.0)
            metrics = self._latest_metrics(
                article_id=article.id, date_from=date_from, date_to=date_to
            )
            rows.append(
                {
                    "article_id": article.id,
                    "title": article.title,
                    "status": article.status,
                    "views": metrics["views"],
                    "revenue_yuan": metrics["revenue_yuan"],
                    "cost": round(cost, 6),
                    "roi": None if cost == 0 else round(metrics["revenue_yuan"] / cost, 3),
                }
            )
        return rows
