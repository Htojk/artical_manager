"""Publishing orchestration with idempotency, retries and manual fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.article_generation.quality import (
    analyze_draft,
    analyze_evidence,
    validate_title,
)
from app.core.constants import ArticleStatus, DEFAULT_PLATFORMS, PublishStatus
from app.core.errors import NotFoundError, ValidationError
from app.core.security import CredentialService
from app.core.tracing import trace_span
from app.models.article import (
    Article,
    DraftVersion,
    Fact,
    FormattedOutput,
    PublishRecord,
    PublishStatusHistory,
    ReviewReport,
    Source,
)
from app.models.base import utcnow
from app.platforms.base import FormatResult
from app.platforms.registry import PlatformRegistry

logger = logging.getLogger(__name__)


@dataclass
class PublishBatchResult:
    records: list[PublishRecord] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


class PublishingService:
    def __init__(
        self,
        session: Session,
        registry: PlatformRegistry,
        credentials: CredentialService,
    ) -> None:
        self.session = session
        self.registry = registry
        self.credentials = credentials

    def _article(self, article_id: str) -> Article:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        return article

    def _quality(self, article_id: str, article: Article) -> dict:
        """Surface the objective signals a human should see before publishing."""
        draft = self.session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )
        review = self.session.scalar(
            select(ReviewReport)
            .where(ReviewReport.article_id == article_id)
            .order_by(ReviewReport.created_at.desc())
        )
        sources = list(
            self.session.scalars(select(Source).where(Source.article_id == article_id))
        )
        facts = list(
            self.session.scalars(select(Fact).where(Fact.article_id == article_id))
        )
        audit = analyze_draft(draft.content_md if draft else "", sources)
        evidence = analyze_evidence(sources, facts)
        title_issues = validate_title(article.title, list(article.target_platforms or []))
        return {
            "review_total": review.total if review else None,
            "review_verdict": review.verdict if review else None,
            "word_count": audit["word_count"],
            "citation_count": audit["citation_count"],
            "dangling_citations": audit["dangling_citations"],
            "cited_source_count": audit["cited_source_count"],
            "source_count": len(sources),
            "fact_count": evidence["fact_count"],
            "verified_fact_count": evidence["verified_fact_count"],
            "low_confidence": evidence["low_confidence"],
            "title_issues": title_issues,
            "warnings": evidence["issues"] + title_issues,
        }

    def confirm_summary(self, article_id: str, platforms: list[str] | None = None) -> dict:
        article = self._article(article_id)
        selected = platforms or list(article.target_platforms or DEFAULT_PLATFORMS)
        items = []
        for platform in selected:
            adapter = self.registry.get(platform)
            output = self.session.scalar(
                select(FormattedOutput).where(
                    FormattedOutput.article_id == article_id,
                    FormattedOutput.platform == platform,
                )
            )
            credential_payload = self.credentials.get(platform)
            availability = (
                adapter.validate(credential_payload)
                if adapter
                else None
            )
            items.append(
                {
                    "platform": platform,
                    "display_name": adapter.display_name if adapter else platform,
                    "title": article.title,
                    "artifact_ready": bool(output and output.status == "ready"),
                    "available": bool(availability and availability.available),
                    "mode": availability.mode if availability else "unavailable",
                    "reason": availability.reason if availability else "未注册平台适配器",
                }
            )
        return {
            "article_id": article_id,
            "title": article.title,
            "platforms": items,
            "quality": self._quality(article_id, article),
        }

    def list_records(self, article_id: str) -> list[PublishRecord]:
        return list(
            self.session.scalars(
                select(PublishRecord)
                .where(PublishRecord.article_id == article_id)
                .order_by(PublishRecord.platform)
            )
        )

    def _get_or_create(self, article_id: str, platform: str) -> PublishRecord:
        record = self.session.scalar(
            select(PublishRecord).where(
                PublishRecord.article_id == article_id, PublishRecord.platform == platform
            )
        )
        if record is None:
            record = PublishRecord(article_id=article_id, platform=platform)
            self.session.add(record)
            self.session.flush()
        return record

    @staticmethod
    def _publish_adapter(
        adapter,
        artifact: FormatResult,
        credentials: dict,
        *,
        platform: str,
        article_id: str,
        attempt: int,
    ):
        """Call the adapter with one span; credentials never enter the trace."""
        with trace_span(
            "publish.platform",
            input={"platform": platform, "article_id": article_id},
            metadata={"platform": platform, "attempt": attempt},
        ) as span:
            try:
                result = adapter.publish(artifact, credentials)
            except Exception as exc:
                if span is not None:
                    span.update(
                        output={"status": "error", "error": str(exc)},
                        level="ERROR",
                        status_message=str(exc),
                    )
                raise
            if span is not None:
                span.update(
                    output={
                        "status": result.status,
                        "success": result.success,
                        "remote_id": result.remote_id,
                    }
                )
            return result

    def _status(self, record: PublishRecord, status: str, source: str) -> None:
        record.status = status
        record.updated_at = utcnow()
        self.session.add(
            PublishStatusHistory(
                publish_record_id=record.id,
                status=status,
                source=source,
            )
        )

    def publish(
        self, article_id: str, platforms: list[str] | None = None
    ) -> PublishBatchResult:
        article = self._article(article_id)
        selected = platforms or list(article.target_platforms or DEFAULT_PLATFORMS)
        result = PublishBatchResult()
        for platform in selected:
            record = self._get_or_create(article_id, platform)
            if record.status in {PublishStatus.PUBLISHED, PublishStatus.DRAFT} and record.remote_id:
                result.skipped.append(platform)
                result.records.append(record)
                continue
            adapter = self.registry.get(platform)
            if adapter is None:
                message = f"未注册平台适配器: {platform}"
                self._status(record, PublishStatus.FAILED, "system")
                record.error = message
                result.errors[platform] = message
                result.records.append(record)
                self.session.commit()
                continue
            credential_payload = self.credentials.get(platform)
            availability = adapter.validate(credential_payload)
            if not adapter.capabilities.publish:
                self._status(record, PublishStatus.MANUAL_REQUIRED, "system")
                record.error = availability.reason or "该平台需要手动发布"
                result.records.append(record)
                self.session.commit()
                continue
            if not availability.available:
                self._status(record, PublishStatus.MANUAL_REQUIRED, "system")
                record.error = availability.reason or "平台凭据不可用"
                result.records.append(record)
                self.session.commit()
                continue
            output = self.session.scalar(
                select(FormattedOutput).where(
                    FormattedOutput.article_id == article_id,
                    FormattedOutput.platform == platform,
                )
            )
            if output is None or output.status != "ready":
                message = f"平台 {platform} 尚未生成可用排版产物"
                self._status(record, PublishStatus.FAILED, "system")
                record.error = message
                result.errors[platform] = message
                result.records.append(record)
                self.session.commit()
                continue
            self._status(record, PublishStatus.PUBLISHING, "system")
            record.attempt += 1
            record.formatted_output_id = output.id
            self.session.commit()
            try:
                artifact = FormatResult(
                    platform=output.platform,
                    title=output.title,
                    summary=output.summary,
                    tags=list(output.tags or []),
                    content=output.content,
                    format=output.format,
                )
                publish_result = self._publish_adapter(
                    adapter,
                    artifact,
                    credential_payload,
                    platform=platform,
                    article_id=article_id,
                    attempt=record.attempt,
                )
                if publish_result.success:
                    is_draft = publish_result.status == "draft"
                    self._status(record, PublishStatus.DRAFT if is_draft else PublishStatus.PUBLISHED, "api")
                    record.remote_id = publish_result.remote_id
                    record.url = publish_result.url
                    record.published_at = None if is_draft else utcnow()
                    record.error = None
                elif publish_result.status == "manual_required":
                    self._status(record, PublishStatus.MANUAL_REQUIRED, "system")
                    record.error = publish_result.error
                else:
                    self._status(record, PublishStatus.FAILED, "api")
                    record.error = publish_result.error
                    result.errors[platform] = publish_result.error or "发布失败"
            except Exception as exc:  # noqa: BLE001 - isolate one platform
                logger.exception("publish failed for platform %s", platform)
                self._status(record, PublishStatus.FAILED, "system")
                record.error = str(exc)
                result.errors[platform] = str(exc)
            result.records.append(record)
            self.session.commit()

        statuses = [record.status for record in result.records]
        if statuses and all(status == PublishStatus.PUBLISHED for status in statuses):
            article.status = ArticleStatus.PUBLISHED
        elif PublishStatus.PUBLISHED in statuses:
            article.status = ArticleStatus.PUBLISHED
        else:
            article.status = ArticleStatus.WAITING_PUBLISH
        self.session.commit()
        return result

    def retry_failed(self, article_id: str) -> PublishBatchResult:
        failed = [
            record.platform
            for record in self.list_records(article_id)
            if record.status in {PublishStatus.FAILED, PublishStatus.UNAVAILABLE}
        ]
        if not failed:
            return PublishBatchResult()
        return self.publish(article_id, failed)

    def manual_backfill(
        self,
        article_id: str,
        *,
        platform: str,
        url: str,
        remote_id: str | None = None,
        status: str = PublishStatus.PUBLISHED,
    ) -> PublishRecord:
        self._article(article_id)
        record = self._get_or_create(article_id, platform)
        self._status(record, status, "user")
        record.url = url
        record.remote_id = remote_id or record.remote_id
        if status == PublishStatus.PUBLISHED:
            record.published_at = utcnow()
        self.session.commit()
        return record

    def history(self, article_id: str, platform: str) -> list[PublishStatusHistory]:
        record = self.session.scalar(
            select(PublishRecord).where(
                PublishRecord.article_id == article_id, PublishRecord.platform == platform
            )
        )
        if record is None:
            raise NotFoundError("发布记录不存在")
        return list(
            self.session.scalars(
                select(PublishStatusHistory)
                .where(PublishStatusHistory.publish_record_id == record.id)
                .order_by(PublishStatusHistory.created_at)
            )
        )
