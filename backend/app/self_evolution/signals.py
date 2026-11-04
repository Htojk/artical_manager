"""Collect user edits, review findings and performance as evolution signals."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import DraftVersion, MetricSnapshot, PublishRecord, ReviewReport


@dataclass
class ArticleSignal:
    article_id: str
    title: str
    review_issues: list[str] = field(default_factory=list)
    review_average: float | None = None
    rework_count: int = 0
    edit_diff: str = ""
    user_edit_chars: int = 0
    views: int = 0
    revenue_cents: int = 0
    cost: float = 0.0

    def as_dict(self) -> dict:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "review_issues": self.review_issues,
            "review_average": self.review_average,
            "rework_count": self.rework_count,
            "edit_diff": self.edit_diff,
            "user_edit_chars": self.user_edit_chars,
            "views": self.views,
            "revenue_cents": self.revenue_cents,
            "cost": self.cost,
        }


class SignalCollector:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_article(self, article_id: str) -> ArticleSignal:
        from app.models.article import Article
        from app.models.llm import LLMCall

        article = self.session.get(Article, article_id)
        if article is None:
            raise ValueError(f"article not found: {article_id}")
        reviews = list(
            self.session.scalars(
                select(ReviewReport)
                .where(ReviewReport.article_id == article_id)
                .order_by(ReviewReport.created_at)
            )
        )
        issues = [
            f"{report.verdict}/{report.rollback_to or '-'}: {report.rationale}"
            for report in reviews
            if report.verdict == "fail"
        ]
        drafts = list(
            self.session.scalars(
                select(DraftVersion)
                .where(DraftVersion.article_id == article_id)
                .order_by(DraftVersion.version)
            )
        )
        diff = ""
        user_edit_chars = 0
        model_draft = next((item for item in drafts if item.created_by == "model"), None)
        latest_user = next(
            (item for item in reversed(drafts) if item.created_by == "user"), None
        )
        if model_draft is not None and latest_user is not None:
            diff_lines = list(
                difflib.unified_diff(
                    model_draft.content_md.splitlines(),
                    latest_user.content_md.splitlines(),
                    fromfile=f"model-v{model_draft.version}",
                    tofile=f"user-v{latest_user.version}",
                    lineterm="",
                )
            )
            diff = "\n".join(diff_lines[:200])
            user_edit_chars = max(0, len(latest_user.content_md) - len(model_draft.content_md))
        records = list(
            self.session.scalars(
                select(PublishRecord).where(PublishRecord.article_id == article_id)
            )
        )
        views = 0
        revenue = 0
        for record in records:
            snapshot = self.session.scalar(
                select(MetricSnapshot)
                .where(MetricSnapshot.publish_record_id == record.id)
                .order_by(MetricSnapshot.captured_at.desc())
            )
            if snapshot is not None:
                views += snapshot.views
                revenue += snapshot.revenue_cents
        from sqlalchemy import func

        cost = self.session.scalar(
            select(func.coalesce(func.sum(LLMCall.cost), 0.0)).where(
                LLMCall.article_id == article_id
            )
        )
        review_average = (
            round(sum(item.total for item in reviews) / len(reviews), 2) if reviews else None
        )
        return ArticleSignal(
            article_id=article_id,
            title=article.title,
            review_issues=issues,
            review_average=review_average,
            rework_count=sum(1 for item in reviews if item.verdict == "fail"),
            edit_diff=diff,
            user_edit_chars=user_edit_chars,
            views=views,
            revenue_cents=revenue,
            cost=float(cost or 0.0),
        )

    def recent(self, limit: int = 20) -> list[ArticleSignal]:
        from app.models.article import Article

        articles = list(
            self.session.scalars(
                select(Article).order_by(Article.updated_at.desc()).limit(limit)
            )
        )
        return [self.for_article(article.id) for article in articles]
