"""Graph state. Only identifiers and lightweight metadata live here."""

from __future__ import annotations

from typing import TypedDict


class ArticleState(TypedDict, total=False):
    article_id: str
    run_id: str
    revision_count: int
    max_revisions: int
    stage_error: str | None
    review_verdict: str | None
    rollback_target: str | None
    pause_requested: bool
    next_node: str | None
    review_human_required: bool
    review_human_decision: str | None
    review_rejection_target: str | None
    human_feedback: str | None
    outline_version: int
    draft_version: int
    title_version: int
    formatted_platforms: list[str]
    publish_result: str | None
    research_low_confidence: bool
