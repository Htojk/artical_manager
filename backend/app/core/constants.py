"""Shared enums and constants for the article autopilot backend."""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    TOPIC = "topic_selection"
    RESEARCH = "research"
    OUTLINE = "outline"
    WRITING = "writing"
    TITLE = "title_optimization"
    REVIEW = "review"
    FORMATTING = "formatting"
    PUBLISHING = "publishing"
    EVOLUTION = "evolution"


STAGE_ORDER: tuple[str, ...] = (
    Stage.TOPIC,
    Stage.RESEARCH,
    Stage.OUTLINE,
    Stage.WRITING,
    Stage.TITLE,
    Stage.REVIEW,
    Stage.FORMATTING,
    Stage.PUBLISHING,
)

# Stages that build an LLM prompt and therefore accept skill bindings.
SKILL_STAGE_KEYS: tuple[str, ...] = (
    Stage.TOPIC,
    Stage.RESEARCH,
    Stage.OUTLINE,
    Stage.WRITING,
    Stage.TITLE,
    Stage.REVIEW,
)

STAGE_LABELS: dict[str, str] = {
    Stage.TOPIC: "选题",
    Stage.RESEARCH: "资料搜索",
    Stage.OUTLINE: "大纲生成",
    Stage.WRITING: "写作",
    Stage.TITLE: "标题优化",
    Stage.REVIEW: "审核",
    Stage.FORMATTING: "分平台排版",
    Stage.PUBLISHING: "发布",
}


class ArticleStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_TOPIC = "waiting_topic"
    WAITING_REVIEW = "waiting_review"
    WAITING_PUBLISH = "waiting_publish"
    PUBLISHED = "published"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_REVIEW = "waiting_review"
    WAITING_PUBLISH = "waiting_publish"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    NEEDS_HUMAN = "needs_human"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PublishStatus(StrEnum):
    PENDING = "pending"
    DRAFT = "draft"
    WAITING_CONFIRM = "waiting_confirm"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    MANUAL_REQUIRED = "manual_required"
    UNAVAILABLE = "unavailable"
    OFFLINE = "offline"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


DEFAULT_PLATFORMS: tuple[str, ...] = ("wechat", "zhihu", "juejin", "csdn")
