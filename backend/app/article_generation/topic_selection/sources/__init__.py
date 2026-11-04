"""Hot-topic source registry: RSS/Atom and HTML list pages."""

from app.article_generation.topic_selection.sources.base import (
    HotSignal,
    HotSourceSpec,
    assign_indices,
    normalize_title,
)
from app.article_generation.topic_selection.sources.collector import HotTopicSource
from app.article_generation.topic_selection.sources.html import parse_html_list
from app.article_generation.topic_selection.sources.rss import parse_feed

__all__ = [
    "HotSignal",
    "HotSourceSpec",
    "HotTopicSource",
    "assign_indices",
    "normalize_title",
    "parse_feed",
    "parse_html_list",
]
