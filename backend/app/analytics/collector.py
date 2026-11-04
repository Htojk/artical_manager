"""Readership / revenue metric collection and manual backfill."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PublishStatus
from app.core.errors import NotFoundError, ValidationError
from app.core.security import CredentialService
from app.models.article import MetricSnapshot, PublishRecord
from app.platforms.registry import PlatformRegistry

logger = logging.getLogger(__name__)


@dataclass
class CollectResult:
    snapshots: list[MetricSnapshot] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    def __init__(
        self,
        session: Session,
        registry: PlatformRegistry,
        credentials: CredentialService,
    ) -> None:
        self.session = session
        self.registry = registry
        self.credentials = credentials

    def collect(self, article_id: str | None = None) -> CollectResult:
        query = select(PublishRecord).where(PublishRecord.status == PublishStatus.PUBLISHED)
        if article_id:
            query = query.where(PublishRecord.article_id == article_id)
        records = list(self.session.scalars(query))
        result = CollectResult()
        for record in records:
            adapter = self.registry.get(record.platform)
            if adapter is None or not adapter.capabilities.metrics:
                result.skipped.append(record.platform)
                continue
            try:
                snapshot = adapter.fetch_metrics(record, self.credentials.get(record.platform))
                if snapshot is None:
                    result.skipped.append(record.platform)
                    continue
                metric = MetricSnapshot(
                    publish_record_id=record.id,
                    platform=record.platform,
                    views=snapshot.views,
                    likes=snapshot.likes,
                    comments=snapshot.comments,
                    shares=snapshot.shares,
                    revenue_cents=snapshot.revenue_cents,
                    source=snapshot.source,
                    captured_at=snapshot.captured_at,
                )
                self.session.add(metric)
                result.snapshots.append(metric)
            except Exception as exc:  # noqa: BLE001 - isolate platform failures
                logger.warning("metric collection failed for %s: %s", record.platform, exc)
                result.errors[record.platform] = str(exc)
        self.session.commit()
        return result

    def add_manual(
        self,
        record_id: str,
        *,
        views: int,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        revenue_cents: int = 0,
    ) -> MetricSnapshot:
        record = self.session.get(PublishRecord, record_id)
        if record is None:
            raise NotFoundError("发布记录不存在")
        if views < 0 or revenue_cents < 0:
            raise ValidationError("阅读量与收益不能为负数")
        snapshot = MetricSnapshot(
            publish_record_id=record.id,
            platform=record.platform,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            revenue_cents=revenue_cents,
            source="manual",
        )
        self.session.add(snapshot)
        self.session.commit()
        return snapshot

    def latest_for_article(self, article_id: str) -> list[MetricSnapshot]:
        records = list(
            self.session.scalars(
                select(PublishRecord).where(PublishRecord.article_id == article_id)
            )
        )
        latest: list[MetricSnapshot] = []
        for record in records:
            snapshot = self.session.scalar(
                select(MetricSnapshot)
                .where(MetricSnapshot.publish_record_id == record.id)
                .order_by(MetricSnapshot.captured_at.desc())
            )
            if snapshot is not None:
                latest.append(snapshot)
        return latest
