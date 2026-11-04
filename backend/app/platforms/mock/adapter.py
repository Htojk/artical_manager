"""A fully functional in-memory platform used for demos and tests."""

from __future__ import annotations

import hashlib
from typing import Any

from app.platforms.base import (
    AdapterAvailability,
    AdapterCapabilities,
    ArticleForFormat,
    FormatResult,
    MetricsSnapshot,
    PlatformAdapter,
    PublishResult,
)


class MockAdapter(PlatformAdapter):
    key = "mock"
    display_name = "演示平台"
    capabilities = AdapterCapabilities(
        format=True, publish=True, metrics=True, official_api=False, manual_fallback=True
    )

    def validate(self, credentials: dict[str, Any]) -> AdapterAvailability:
        return AdapterAvailability(available=True, mode="mock")

    def format(self, article: ArticleForFormat) -> FormatResult:
        tags = article.tags or ["演示", "自动化"]
        body = article.content_md.strip()
        if not body.startswith("#"):
            body = f"# {article.title}\n\n{body}"
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary or article.title,
            tags=tags,
            content=body,
            format="markdown",
            metadata={"preview": f"<article><h1>{article.title}</h1></article>"},
        )

    def publish(self, artifact: FormatResult, credentials: dict[str, Any]) -> PublishResult:
        digest = hashlib.sha256(
            f"{artifact.title}:{artifact.content}".encode("utf-8")
        ).hexdigest()[:16]
        return PublishResult(
            success=True,
            remote_id=f"mock-{digest}",
            url=f"https://mock.local/articles/{digest}",
            status="published",
            mode="mock",
            raw={"title": artifact.title},
        )

    def fetch_metrics(self, record: Any, credentials: dict[str, Any]) -> MetricsSnapshot:
        remote_id = getattr(record, "remote_id", "") or "mock"
        seed = int(hashlib.sha256(remote_id.encode("utf-8")).hexdigest()[:8], 16)
        base = seed % 900 + 100
        return MetricsSnapshot(
            views=base,
            likes=base // 10,
            comments=base // 40,
            shares=base // 25,
            revenue_cents=base // 5,
            source="api",
        )
