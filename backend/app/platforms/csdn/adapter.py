"""CSDN adapter: Markdown export with abstract / category metadata."""

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


class CsdnAdapter(PlatformAdapter):
    key = "csdn"
    display_name = "CSDN"
    capabilities = AdapterCapabilities(
        format=True, publish=False, metrics=False, official_api=False, manual_fallback=True
    )

    def validate(self, credentials: dict[str, Any]) -> AdapterAvailability:
        if credentials.get("cookie"):
            return AdapterAvailability(
                available=True,
                mode="export_manual",
                reason="已保存 Cookie；CSDN 默认导出后手动发布",
            )
        return AdapterAvailability(
            available=True, mode="export_manual", reason="未配置 Cookie，导出 Markdown 后手动发布"
        )

    def format(self, article: ArticleForFormat) -> FormatResult:
        tags = article.tags or ["人工智能", "自动化"]
        content = article.content_md.strip()
        if not content.startswith("#"):
            content = f"# {article.title}\n\n{content}"
        front_matter = (
            "---\n"
            f"title: {article.title}\n"
            f"description: {article.summary}\n"
            f"tags: [{', '.join(tags)}]\n"
            "categories: [技术分享]\n"
            "---\n\n"
        )
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary,
            tags=tags,
            content=front_matter + content,
            format="markdown",
            metadata={"editor": "csdn", "abstract": article.summary},
        )

    def publish(self, artifact: FormatResult, credentials: dict[str, Any]) -> PublishResult:
        return PublishResult(
            success=False,
            mode="export_manual",
            status="manual_required",
            error="CSDN 需要导出 Markdown 后手动发布",
        )
