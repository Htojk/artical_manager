"""Zhihu adapter: Markdown export with optional manual publishing."""

from __future__ import annotations

from typing import Any

from app.platforms.base import (
    AdapterAvailability,
    AdapterCapabilities,
    ArticleForFormat,
    FormatResult,
    PlatformAdapter,
    PublishResult,
)


class ZhihuAdapter(PlatformAdapter):
    key = "zhihu"
    display_name = "知乎"
    capabilities = AdapterCapabilities(
        format=True, publish=False, metrics=False, official_api=False, manual_fallback=True
    )

    def validate(self, credentials: dict[str, Any]) -> AdapterAvailability:
        if credentials.get("token") or credentials.get("cookie"):
            return AdapterAvailability(
                available=True,
                mode="export_manual",
                reason="已保存凭据；知乎暂无稳定官方发布接口，默认导出后手动发布",
            )
        return AdapterAvailability(
            available=True,
            mode="export_manual",
            reason="未配置凭据，可导出 Markdown 后手动发布",
        )

    def format(self, article: ArticleForFormat) -> FormatResult:
        tags = article.tags or ["科技", "人工智能"]
        content = article.content_md.strip()
        if not content.startswith("#"):
            content = f"# {article.title}\n\n{content}"
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary,
            tags=tags,
            content=content,
            format="markdown",
            metadata={"editor": "zhihu", "topics": tags[:3]},
        )

    def publish(self, artifact: FormatResult, credentials: dict[str, Any]) -> PublishResult:
        return PublishResult(
            success=False,
            mode="export_manual",
            status="manual_required",
            error="知乎需要导出 Markdown 后手动发布，或使用平台官方开放能力",
        )
