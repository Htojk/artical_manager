"""Shared types for hot-topic sources."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import HotSourceSpec

DEFAULT_ITEM_SELECTOR = "article, li"
USER_AGENT = "ArticleAutopilot/0.1 (+local)"

__all__ = [
    "DEFAULT_ITEM_SELECTOR",
    "HotSignal",
    "HotSourceSpec",
    "USER_AGENT",
    "assign_indices",
    "normalize_title",
]


@dataclass
class HotSignal:
    """A title-level hot signal. Body text is never carried here."""

    title: str
    source: str
    url: str = ""
    published_at: str | None = None
    heat: int = 0
    index: int = 0
    summary: str = ""

    def prompt_payload(self) -> dict:
        """Fields allowed to reach the topic-selection prompt."""
        return {
            "index": self.index,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at,
        }


def normalize_title(title: str) -> str:
    return " ".join((title or "").split()).lower()


def assign_indices(signals: list[HotSignal]) -> list[HotSignal]:
    for position, signal in enumerate(signals, start=1):
        signal.index = position
    return signals
