"""Per-platform formatting orchestrated through the adapter registry."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.article_generation.quality import title_limit
from app.article_generation.formatting.memecub import MemecubClient, enrich_markdown
from app.core.config import get_settings
from app.core.constants import DEFAULT_PLATFORMS
from app.core.errors import ValidationError
from app.core.security import CredentialService
from app.models.article import Article, DraftVersion, FormattedOutput, FormattingSource
from app.platforms.base import ArticleForFormat
from app.platforms.registry import PlatformRegistry

logger = logging.getLogger(__name__)


@dataclass
class FormatBatchResult:
    outputs: list[FormattedOutput] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class FormattingService:
    def __init__(
        self,
        session: Session,
        registry: PlatformRegistry,
        credentials: CredentialService,
        llm: object | None = None,
        memecub_client: MemecubClient | None = None,
    ) -> None:
        self.session = session
        self.registry = registry
        self.credentials = credentials
        self.llm = llm
        self.memecub_client = memecub_client

    def latest_draft(self, article_id: str) -> DraftVersion:
        draft = self.session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )
        if draft is None:
            raise ValidationError("尚无正文可排版")
        return draft

    def list_outputs(self, article_id: str) -> list[FormattedOutput]:
        return list(
            self.session.scalars(
                select(FormattedOutput)
                .where(FormattedOutput.article_id == article_id)
                .order_by(FormattedOutput.platform)
            )
        )

    def format_article(
        self, article_id: str, platforms: list[str] | None = None
    ) -> FormatBatchResult:
        article = self.session.get(Article, article_id)
        if article is None:
            raise ValidationError(f"文章不存在: {article_id}")
        draft = self.latest_draft(article_id)
        selected = platforms or list(article.target_platforms or DEFAULT_PLATFORMS)
        result = FormatBatchResult()
        content_md = draft.content_md
        settings = get_settings()
        if settings.memecub_enabled:
            cached = self.session.scalar(
                select(FormattingSource).where(FormattingSource.draft_id == draft.id)
            )
            if cached is not None:
                content_md = cached.content_md
            elif not settings.memecub_api_key and self.memecub_client is None:
                result.warnings.append("Memecub 已启用但未配置 API Key，未插入表情包")
            else:
                client = self.memecub_client or MemecubClient(
                    settings.memecub_api_key, timeout=settings.memecub_timeout_seconds
                )
                try:
                    content_md, warning = enrich_markdown(
                        content_md, article_id=article_id, client=client, llm=self.llm,
                        commercial_only=True,
                    )
                    if warning:
                        result.warnings.append(warning)
                    else:
                        self.session.add(FormattingSource(
                            article_id=article_id, draft_id=draft.id, content_md=content_md
                        ))
                        try:
                            self.session.commit()
                        except IntegrityError:
                            # Another formatting request may have saved this draft first.
                            self.session.rollback()
                            saved = self.session.scalar(
                                select(FormattingSource).where(FormattingSource.draft_id == draft.id)
                            )
                            if saved is None:
                                raise
                            content_md = saved.content_md
                except Exception as exc:  # noqa: BLE001 - formatting stays usable
                    self.session.rollback()
                    logger.warning("Memecub enrichment failed: %s", exc)
                    result.warnings.append("Memecub 配图失败，已使用原文排版")
                finally:
                    if self.memecub_client is None:
                        client.close()
        for platform in selected:
            adapter = self.registry.get(platform)
            existing = self.session.scalar(
                select(FormattedOutput).where(
                    FormattedOutput.article_id == article_id,
                    FormattedOutput.platform == platform,
                )
            )
            if adapter is None:
                message = f"未注册平台适配器: {platform}"
                result.errors[platform] = message
                if existing is None:
                    existing = FormattedOutput(
                        article_id=article_id, platform=platform, status="failed", error=message
                    )
                    self.session.add(existing)
                else:
                    existing.status = "failed"
                    existing.error = message
                existing.warning = "；".join(result.warnings) or None
                self.session.commit()
                continue
            try:
                artifact = adapter.format(
                    ArticleForFormat(
                        article_id=article_id,
                        title=article.title,
                        content_md=content_md,
                        summary=draft.summary,
                        tags=[],
                        target_platform=platform,
                    )
                )
                if not (artifact.content or "").strip():
                    raise ValidationError("排版产物正文为空")
                if not (artifact.title or "").strip():
                    raise ValidationError("排版产物标题为空")
                limit = title_limit([platform])
                if len(artifact.title) > limit:
                    raise ValidationError(
                        f"标题超过 {platform} 平台上限 {limit} 字（当前 {len(artifact.title)} 字）"
                    )
                if existing is None:
                    existing = FormattedOutput(article_id=article_id, platform=platform)
                    self.session.add(existing)
                existing.title = artifact.title
                existing.summary = artifact.summary
                existing.tags = artifact.tags
                existing.content = artifact.content
                existing.format = artifact.format
                existing.status = "ready"
                existing.error = None
                existing.warning = "；".join(result.warnings) or None
                result.outputs.append(existing)
            except Exception as exc:  # noqa: BLE001 - isolate one platform
                logger.exception("formatting failed for platform %s", platform)
                message = str(exc)
                result.errors[platform] = message
                if existing is None:
                    existing = FormattedOutput(article_id=article_id, platform=platform)
                    self.session.add(existing)
                existing.status = "failed"
                existing.error = message
                existing.warning = "；".join(result.warnings) or None
            self.session.commit()
        return result

    def retry(self, article_id: str, platform: str) -> FormattedOutput:
        result = self.format_article(article_id, [platform])
        if platform in result.errors:
            raise ValidationError(result.errors[platform])
        return result.outputs[0]
