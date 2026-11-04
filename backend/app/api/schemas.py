"""Request payloads for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ArticleCreate(BaseModel):
    title: str = ""
    topic_mode: Literal["manual", "ai"] = "manual"
    target_platforms: list[str] = Field(default_factory=list)
    publish_confirmation: bool | None = None
    angle: str = ""


class ArticleUpdate(BaseModel):
    title: str | None = None
    target_platforms: list[str] | None = None
    publish_confirmation: bool | None = None


class TopicCreate(BaseModel):
    title: str
    angle: str = ""
    rationale: str = "用户手动输入"
    target_platforms: list[str] | None = None
    content_format: Literal["hot_take", "tool_test", "creative_experiment"] = "hot_take"


class TopicUpdate(BaseModel):
    title: str | None = None
    angle: str | None = None
    rationale: str | None = None
    content_format: Literal["hot_take", "tool_test", "creative_experiment"] | None = None


class SourceCreate(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""


class RecommendRequest(BaseModel):
    domain: str = ""
    exclude_titles: list[str] = Field(default_factory=list)


class OutlineEdit(BaseModel):
    content: dict[str, Any]
    note: str = "用户编辑"


class DraftEdit(BaseModel):
    content_md: str
    summary: str = ""
    title: str | None = None


class TitleEdit(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    note: str = "用户选择"


class ConfirmPublish(BaseModel):
    decision: Literal["approve", "cancel"] = "approve"


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    feedback: str = ""


class PublishRequest(BaseModel):
    platforms: list[str] | None = None


class ManualPublish(BaseModel):
    url: str
    remote_id: str | None = None
    status: Literal["published", "offline", "failed"] = "published"


class ManualMetrics(BaseModel):
    views: int = Field(ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    revenue_cents: int = Field(default=0, ge=0)


class ModelCreate(BaseModel):
    name: str
    provider: str = "openai-compatible"
    base_url: str = ""
    api_key_env: str = "APP_LLM_API_KEY"
    model: str
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    currency: str = "CNY"
    context_window: int = 65536
    enabled: bool = True


class ModelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    currency: str | None = None
    context_window: int | None = None
    enabled: bool | None = None


class StageBindingUpdate(BaseModel):
    model_profile_id: str
    temperature: float = 0.7
    max_tokens: int = 8192


class SkillBindRequest(BaseModel):
    stage: str
    slug: str
    order: int = 0
    enabled: bool = True


class SkillCreate(BaseModel):
    slug: str
    description: str
    display_name: str = ""
    content: str = ""
    version: str = "1.0.0"
    applies_to: list[str] = Field(default_factory=list)


class SkillEdit(BaseModel):
    content: str
    note: str = "用户编辑"


class SkillToggle(BaseModel):
    enabled: bool


class CredentialUpdate(BaseModel):
    payload: dict[str, str]


class SettingUpdate(BaseModel):
    value: Any


class DecisionRequest(BaseModel):
    note: str = ""
