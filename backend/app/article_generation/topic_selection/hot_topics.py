"""Backward-compatible imports for hot-topic sources.

The implementation lives in ``sources/`` (RSS, HTML, collector). This module
keeps the old import path working for existing callers and tests.
"""

from app.article_generation.topic_selection.sources import (
    HotSignal,
    HotSourceSpec,
    HotTopicSource,
    assign_indices,
    normalize_title,
    parse_feed,
    parse_html_list,
)

__all__ = [
    "HotSignal",
    "HotSourceSpec",
    "HotTopicSource",
    "assign_indices",
    "normalize_title",
    "parse_feed",
    "parse_html_list",
]
