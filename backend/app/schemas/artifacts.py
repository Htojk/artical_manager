"""Pydantic contracts for structured LLM outputs and artifacts."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TopicCandidate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    angle: str = Field(min_length=5)
    rationale: str = Field(min_length=5)
    target_platforms: list[str] = Field(default_factory=list)
    hot_signal: str = ""
    hot_signal_index: int = Field(default=0, ge=0)
    discussion_score: float = Field(default=0, ge=0, le=100)
    discussion_reason: str = ""
    content_format: str = "hot_take"
    entertainment_scores: dict[str, float] = Field(default_factory=dict)
    entertainment_reason: str = ""

    @field_validator("hot_signal_index", mode="before")
    @classmethod
    def _normalize_signal_index(cls, value: object) -> int:
        try:
            return max(0, int(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @field_validator("discussion_score", mode="before")
    @classmethod
    def _normalize_discussion_score(cls, value: object) -> float:
        if value is None or value == "":
            return 0.0
        try:
            return min(100.0, max(0.0, float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0


class TopicCandidates(BaseModel):
    candidates: list[TopicCandidate]


class ExtractedSource(BaseModel):
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None


class ExtractedFact(BaseModel):
    statement: str
    source_index: int = Field(default=0, description="1-based index into sources; 0 means unverified")


class ResearchOutput(BaseModel):
    sources: list[ExtractedSource] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    low_confidence: bool = False
    notes: str = ""


class OutlineSection(BaseModel):
    heading: str
    key_points: list[str] = Field(default_factory=list)
    source_refs: list[int] = Field(default_factory=list)
    image_hint: str = ""


class OutlineOutput(BaseModel):
    title: str
    hook: str
    sections: list[OutlineSection]
    target_words: int = 1800
    content_format: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class DraftOutput(BaseModel):
    title: str
    summary: str
    content_md: str
    tags: list[str] = Field(default_factory=list)


class RevisedSection(BaseModel):
    heading: str
    content_md: str


class TargetedRevisionOutput(BaseModel):
    sections: list[RevisedSection]
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class TitleCandidate(BaseModel):
    title: str = Field(min_length=4, max_length=120)
    style: str = Field(default="", description="数字型 | 悬念型 | 干货型 | 对比型 | 痛点型")
    rationale: str = ""
    score: float = Field(default=0, ge=0, le=100)


class TitleOptimizationOutput(BaseModel):
    candidates: list[TitleCandidate]
    recommended: str = ""
    strategy: str = ""

    @field_validator("recommended", mode="before")
    @classmethod
    def _coerce_recommended(cls, value: object) -> object:
        # Some models return the recommended candidate object instead of its
        # title string; accept both shapes.
        if isinstance(value, dict):
            return str(value.get("title") or value.get("recommended") or "")
        return value


class ReviewIssue(BaseModel):
    location: str = ""
    description: str
    severity: str = Field(default="minor", description="critical | major | minor")


class ReviewDimension(BaseModel):
    dimension: str = Field(description="fact | structure | readability | compliance | originality")
    score: float = Field(ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    dimensions: list[ReviewDimension]
    summary: str = ""


class RejectionRoute(BaseModel):
    rollback_to: str = Field(description="research | outline | writing")
    reason: str = ""


class EvolvingSuggestion(BaseModel):
    type: str = Field(description="writing_rule | skill_update | prompt_update | model_routing")
    target_stage: str
    title: str
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    patch: dict = Field(default_factory=dict)
    expected_impact: str = ""


class EvolvingSuggestions(BaseModel):
    suggestions: list[EvolvingSuggestion]
