"""The single adapter contract implemented by every platform package."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar


@dataclass(frozen=True)
class AdapterCapabilities:
    format: bool = True
    publish: bool = False
    metrics: bool = False
    official_api: bool = False
    manual_fallback: bool = True


@dataclass
class AdapterAvailability:
    available: bool
    mode: str = "export_manual"
    reason: str | None = None


@dataclass
class ArticleForFormat:
    article_id: str
    title: str
    content_md: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    target_platform: str = ""


@dataclass
class FormatResult:
    platform: str
    title: str
    summary: str
    tags: list[str]
    content: str
    format: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    success: bool
    remote_id: str | None = None
    url: str | None = None
    status: str = "published"
    error: str | None = None
    mode: str = "api"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsSnapshot:
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    revenue_cents: int = 0
    source: str = "api"
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PlatformAdapter(ABC):
    """Every sibling platform package implements this interface."""

    key: ClassVar[str]
    display_name: ClassVar[str]
    capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities()

    @abstractmethod
    def validate(self, credentials: dict[str, Any]) -> AdapterAvailability:
        """Return whether the platform can be used with the given credentials."""

    @abstractmethod
    def format(self, article: ArticleForFormat) -> FormatResult:
        """Render the article for this platform."""

    @abstractmethod
    def publish(self, artifact: FormatResult, credentials: dict[str, Any]) -> PublishResult:
        """Push the artifact to the platform (or report that manual publishing is required)."""

    def fetch_metrics(
        self, record: Any, credentials: dict[str, Any]
    ) -> MetricsSnapshot | None:
        """Fetch readership metrics. Return None when the platform has no usable API."""
        return None

    def export(self, artifact: FormatResult) -> bytes:
        return artifact.content.encode("utf-8")
