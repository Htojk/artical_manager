"""Conditional edge decisions for the article workflow."""

from __future__ import annotations

from app.article_generation.workflow.state import ArticleState
from app.core.constants import Stage


def route_after_stage(state: ArticleState) -> str:
    if state.get("stage_error"):
        return "halt"
    if state.get("pause_requested"):
        return "pause"
    return "continue"


def route_after_review(state: ArticleState) -> str:
    if state.get("stage_error"):
        return "halt"
    if state.get("pause_requested"):
        return "pause"
    if state.get("review_human_required"):
        return "review_decision"
    if state.get("review_verdict") == "pass":
        return "format"
    if int(state.get("revision_count", 0)) >= int(state.get("max_revisions", 3)):
        return "halt"
    target = state.get("rollback_target") or Stage.WRITING
    if target not in {Stage.RESEARCH, Stage.OUTLINE, Stage.WRITING}:
        target = Stage.WRITING
    return {
        Stage.RESEARCH: "research",
        Stage.OUTLINE: "outline",
        Stage.WRITING: "write",
    }[target]


def route_after_review_decision(state: ArticleState) -> str:
    if state.get("review_human_decision") == "approve":
        return "format"
    target = state.get("review_rejection_target") or Stage.WRITING
    if target not in {Stage.RESEARCH, Stage.OUTLINE, Stage.WRITING}:
        target = Stage.WRITING
    return {
        Stage.RESEARCH: "research",
        Stage.OUTLINE: "outline",
        Stage.WRITING: "write",
    }[target]


def route_pause(state: ArticleState) -> str:
    target = state.get("next_node")
    if target in {
        "research",
        "outline",
        "write",
        "title",
        "review",
        "review_decision",
        "format",
        "publish",
    }:
        return target
    return "halt"
