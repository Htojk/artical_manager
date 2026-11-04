"""Article, workflow and publishing ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    ArticleStatus,
    PublishStatus,
    RunStatus,
    StageStatus,
)
from app.models.base import Base, new_id, utcnow


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(32), default=ArticleStatus.DRAFT, index=True)
    current_stage: Mapped[str] = mapped_column(String(32), default="topic_selection")
    topic_mode: Mapped[str] = mapped_column(String(16), default="manual")
    target_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    publish_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    current_topic_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_outline_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_draft_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_title_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    runs: Mapped[list["WorkflowRun"]] = relationship(
        back_populates="article", cascade="all, delete-orphan", passive_deletes=True
    )
    topics: Mapped[list["Topic"]] = relationship(back_populates="article", cascade="all, delete-orphan")
    sources: Mapped[list["Source"]] = relationship(back_populates="article", cascade="all, delete-orphan")
    facts: Mapped[list["Fact"]] = relationship(back_populates="article", cascade="all, delete-orphan")
    outline_versions: Mapped[list["OutlineVersion"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    draft_versions: Mapped[list["DraftVersion"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    title_versions: Mapped[list["TitleVersion"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    review_reports: Mapped[list["ReviewReport"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    formatted_outputs: Mapped[list["FormattedOutput"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    formatting_sources: Mapped[list["FormattingSource"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    publish_records: Mapped[list["PublishRecord"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.PENDING, index=True)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    max_revisions: Mapped[int] = mapped_column(Integer, default=3)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    article: Mapped["Article"] = relationship(back_populates="runs")
    stage_runs: Mapped[list["StageRun"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class StageRun(Base):
    __tablename__ = "stage_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default=StageStatus.PENDING)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["WorkflowRun"] = relationship(back_populates="stage_runs")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="manual")
    title: Mapped[str] = mapped_column(String(500))
    angle: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    target_platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    hot_signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    discussion_score: Mapped[float] = mapped_column(Float, default=0.0)
    discussion_reason: Mapped[str] = mapped_column(Text, default="")
    entertainment_score: Mapped[float] = mapped_column(Float, default=0.0)
    entertainment_reason: Mapped[str] = mapped_column(Text, default="")
    entertainment_scores: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    content_format: Mapped[str] = mapped_column(String(40), default="hot_take")
    selected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="topics")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    credibility: Mapped[str] = mapped_column(String(16), default="medium")
    credibility_reason: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)
    added_by: Mapped[str] = mapped_column(String(16), default="agent")

    article: Mapped["Article"] = relationship(back_populates="sources")


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="verified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="facts")
    source: Mapped["Source | None"] = relationship()


class OutlineVersion(Base):
    __tablename__ = "outline_versions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_outline_article_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(16), default="model")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="outline_versions")


class DraftVersion(Base):
    __tablename__ = "draft_versions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_draft_article_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    content_md: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    skill_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    citation_report: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(16), default="model")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="draft_versions")


class TitleVersion(Base):
    __tablename__ = "title_versions"
    __table_args__ = (UniqueConstraint("article_id", "version", name="uq_title_article_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    selected_title: Mapped[str] = mapped_column(String(500), default="")
    strategy: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(16), default="model")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="title_versions")


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    draft_version_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("draft_versions.id", ondelete="SET NULL"), nullable=True
    )
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), default="fail")
    rollback_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    config_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="review_reports")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("review_reports.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(16), default="approved")
    feedback: Mapped[str] = mapped_column(Text, default="")
    rollback_to: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FormattingSource(Base):
    """The licensed image selection shared by every platform for one draft."""

    __tablename__ = "formatting_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("draft_versions.id", ondelete="CASCADE"), unique=True, index=True
    )
    content_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped["Article"] = relationship(back_populates="formatting_sources")


class FormattedOutput(Base):
    __tablename__ = "formatted_outputs"
    __table_args__ = (UniqueConstraint("article_id", "platform", name="uq_format_article_platform"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(16), default="markdown")
    status: Mapped[str] = mapped_column(String(24), default="ready")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    article: Mapped["Article"] = relationship(back_populates="formatted_outputs")


class PublishRecord(Base):
    __tablename__ = "publish_records"
    __table_args__ = (UniqueConstraint("article_id", "platform", name="uq_publish_article_platform"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    article_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), index=True)
    formatted_output_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("formatted_outputs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default=PublishStatus.PENDING, index=True)
    remote_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    article: Mapped["Article"] = relationship(back_populates="publish_records")
    formatted_output: Mapped["FormattedOutput | None"] = relationship()
    metrics: Mapped[list["MetricSnapshot"]] = relationship(
        back_populates="publish_record", cascade="all, delete-orphan"
    )
    history: Mapped[list["PublishStatusHistory"]] = relationship(
        back_populates="publish_record", cascade="all, delete-orphan"
    )


class PublishStatusHistory(Base):
    __tablename__ = "publish_status_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    publish_record_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("publish_records.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(24), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    publish_record: Mapped["PublishRecord"] = relationship(back_populates="history")


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    publish_record_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("publish_records.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="api")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    publish_record: Mapped["PublishRecord"] = relationship(back_populates="metrics")
