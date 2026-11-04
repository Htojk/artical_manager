"""Fetch and normalize hot signals from all configured sources."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.article_generation.topic_selection.sources.base import (
    USER_AGENT,
    HotSignal,
    HotSourceSpec,
    assign_indices,
    normalize_title,
)
from app.article_generation.topic_selection.sources.html import parse_html_list
from app.article_generation.topic_selection.sources.rss import parse_feed
from app.core.tracing import trace_span

logger = logging.getLogger(__name__)


def _contains_keyword(text: str, keyword: str) -> bool:
    word = keyword.casefold()
    if word in {"ai", "gpt", "llm", "mcp", "fun"}:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text))
    return word in text


def _signal_text(signal: HotSignal, spec: HotSourceSpec) -> str:
    return (f"{signal.title} {signal.summary}" if spec.match_summary else signal.title).casefold()


def _matches_keywords(signal: HotSignal, spec: HotSourceSpec) -> bool:
    if not spec.include_keywords:
        return True
    text = _signal_text(signal, spec)
    return any(_contains_keyword(text, keyword) for keyword in spec.include_keywords)


def _priority_score(signal: HotSignal, spec: HotSourceSpec) -> int:
    text = _signal_text(signal, spec)
    return sum(_contains_keyword(text, word) for word in spec.priority_keywords)


@dataclass
class HotTopicSource:
    feed_urls: list[str] = field(default_factory=list)
    timeout: float = 8.0
    errors: list[str] = field(default_factory=list)
    specs: list[HotSourceSpec] | None = None
    per_source_limit: int = 20

    def __post_init__(self) -> None:
        if self.specs is None:
            self.specs = [
                HotSourceSpec(name=urlparse(url).netloc or url, kind="rss", url=url)
                for url in self.feed_urls
            ]

    def fetch(self, limit: int = 10) -> list[HotSignal]:
        self.errors = []
        if limit <= 0:
            return []
        buckets: list[list[HotSignal]] = []
        for spec in self.specs or []:
            with trace_span(
                "source.fetch",
                input={"source": spec.name, "url": spec.url},
                metadata={"source": spec.name, "kind": spec.kind},
            ) as span:
                try:
                    response = httpx.get(
                        spec.url,
                        timeout=self.timeout,
                        follow_redirects=True,
                        headers={"User-Agent": USER_AGENT},
                    )
                    response.raise_for_status()
                    if spec.kind == "html":
                        items = parse_html_list(
                            response.text, spec, limit=self.per_source_limit
                        )
                    else:
                        items = parse_feed(
                            response.text, spec.url, source_name=spec.name
                        )[: self.per_source_limit]
                    relevant = [item for item in items if _matches_keywords(item, spec)]
                    relevant.sort(key=lambda item: _priority_score(item, spec), reverse=True)
                except Exception as exc:  # noqa: BLE001 - one source must not block others
                    self.errors.append(f"{spec.name} ({spec.url}): {exc}")
                    logger.warning("hot topic source failed %s: %s", spec.url, exc)
                    if span is not None:
                        span.update(
                            output={"source": spec.name, "status": "error", "error": str(exc)},
                            level="ERROR",
                            status_message=str(exc),
                        )
                    continue
                if span is not None:
                    span.update(
                        output={
                            "source": spec.name,
                            "status": "ok",
                            "count": len(items),
                            "relevant_count": len(relevant),
                        }
                    )
            buckets.append(relevant)

        deduped: list[HotSignal] = []
        seen: set[str] = set()
        for position in range(max((len(bucket) for bucket in buckets), default=0)):
            for bucket in buckets:
                if position >= len(bucket):
                    continue
                signal = bucket[position]
                key = normalize_title(signal.title)
                if key and key not in seen:
                    seen.add(key)
                    deduped.append(signal)
                    if len(deduped) == limit:
                        return assign_indices(deduped)
        return assign_indices(deduped)
