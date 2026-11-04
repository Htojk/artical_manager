"""ORM to JSON-friendly payload helpers used by the routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.article import (
    Article,
    DraftVersion,
    Fact,
    FormattedOutput,
    MetricSnapshot,
    OutlineVersion,
    PublishRecord,
    PublishStatusHistory,
    ReviewDecision,
    ReviewReport,
    Source,
    StageRun,
    TitleVersion,
    Topic,
    WorkflowRun,
)
from app.models.evolution import EvolutionSuggestion
from app.models.llm import LLMCall, ModelProfile, StageModelBinding
from app.models.skill import Skill, SkillBinding


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def article_payload(article: Article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "status": article.status,
        "current_stage": article.current_stage,
        "topic_mode": article.topic_mode,
        "target_platforms": list(article.target_platforms or []),
        "publish_confirmation": article.publish_confirmation,
        "current_topic_id": article.current_topic_id,
        "current_outline_version": article.current_outline_version,
        "current_draft_version": article.current_draft_version,
        "current_title_version": article.current_title_version,
        "error": article.error,
        "created_at": _dt(article.created_at),
        "updated_at": _dt(article.updated_at),
    }


def topic_payload(topic: Topic) -> dict:
    return {
        "id": topic.id,
        "article_id": topic.article_id,
        "source": topic.source,
        "title": topic.title,
        "angle": topic.angle,
        "rationale": topic.rationale,
        "target_platforms": list(topic.target_platforms or []),
        "hot_signals": list(topic.hot_signals or []),
        "discussion_score": float(topic.discussion_score or 0),
        "discussion_reason": topic.discussion_reason or "",
        "entertainment_score": float(topic.entertainment_score or 0),
        "entertainment_reason": topic.entertainment_reason or "",
        "entertainment_scores": dict(topic.entertainment_scores or {}),
        "content_format": topic.content_format or "hot_take",
        "selected": topic.selected,
        "created_at": _dt(topic.created_at),
    }


def run_payload(run: WorkflowRun) -> dict:
    return {
        "id": run.id,
        "article_id": run.article_id,
        "thread_id": run.thread_id,
        "status": run.status,
        "current_stage": run.current_stage,
        "revision_count": run.revision_count,
        "max_revisions": run.max_revisions,
        "pause_requested": run.pause_requested,
        "error": run.error,
        "created_at": _dt(run.created_at),
        "updated_at": _dt(run.updated_at),
    }


def stage_run_payload(stage_run: StageRun) -> dict:
    return {
        "id": stage_run.id,
        "run_id": stage_run.run_id,
        "stage": stage_run.stage,
        "attempt": stage_run.attempt,
        "status": stage_run.status,
        "started_at": _dt(stage_run.started_at),
        "finished_at": _dt(stage_run.finished_at),
        "model": stage_run.model,
        "prompt_tokens": stage_run.prompt_tokens,
        "completion_tokens": stage_run.completion_tokens,
        "cost": stage_run.cost,
        "error": stage_run.error,
    }


def source_payload(source: Source) -> dict:
    return {
        "id": source.id,
        "title": source.title,
        "url": source.url,
        "snippet": source.snippet,
        "published_at": source.published_at,
        "fetched_at": _dt(source.fetched_at),
        "credibility": source.credibility,
        "credibility_reason": source.credibility_reason,
        "added_by": source.added_by,
    }


def fact_payload(fact: Fact) -> dict:
    return {
        "id": fact.id,
        "source_id": fact.source_id,
        "statement": fact.statement,
        "status": fact.status,
        "created_at": _dt(fact.created_at),
    }


def outline_payload(outline: OutlineVersion) -> dict:
    return {
        "id": outline.id,
        "version": outline.version,
        "content": outline.content,
        "created_by": outline.created_by,
        "note": outline.note,
        "created_at": _dt(outline.created_at),
    }


def draft_payload(draft: DraftVersion) -> dict:
    return {
        "id": draft.id,
        "version": draft.version,
        "content_md": draft.content_md,
        "summary": draft.summary,
        "word_count": draft.word_count,
        "model": draft.model,
        "skill_snapshot": list(draft.skill_snapshot or []),
        "citation_report": list(draft.citation_report or []),
        "prompt_tokens": draft.prompt_tokens,
        "completion_tokens": draft.completion_tokens,
        "duration_ms": draft.duration_ms,
        "created_by": draft.created_by,
        "note": draft.note,
        "created_at": _dt(draft.created_at),
    }


def title_payload(version: TitleVersion) -> dict:
    return {
        "id": version.id,
        "version": version.version,
        "candidates": list(version.candidates or []),
        "selected_title": version.selected_title,
        "strategy": version.strategy,
        "model": version.model,
        "prompt_tokens": version.prompt_tokens,
        "completion_tokens": version.completion_tokens,
        "duration_ms": version.duration_ms,
        "created_by": version.created_by,
        "note": version.note,
        "created_at": _dt(version.created_at),
    }


def review_payload(report: ReviewReport) -> dict:
    return {
        "id": report.id,
        "draft_version_id": report.draft_version_id,
        "scores": report.scores,
        "total": report.total,
        "verdict": report.verdict,
        "rollback_to": report.rollback_to,
        "rationale": report.rationale,
        "model": report.model,
        "config_version": report.config_version,
        "created_at": _dt(report.created_at),
    }


def review_decision_payload(decision: ReviewDecision) -> dict:
    return {
        "id": decision.id,
        "article_id": decision.article_id,
        "run_id": decision.run_id,
        "report_id": decision.report_id,
        "decision": decision.decision,
        "feedback": decision.feedback,
        "rollback_to": decision.rollback_to,
        "target_reason": decision.target_reason,
        "created_at": _dt(decision.created_at),
    }


def format_payload(output: FormattedOutput) -> dict:
    return {
        "id": output.id,
        "platform": output.platform,
        "title": output.title,
        "summary": output.summary,
        "tags": list(output.tags or []),
        "content": output.content,
        "format": output.format,
        "status": output.status,
        "error": output.error,
        "warning": output.warning,
        "created_at": _dt(output.created_at),
        "updated_at": _dt(output.updated_at),
    }


def publish_payload(record: PublishRecord) -> dict:
    return {
        "id": record.id,
        "article_id": record.article_id,
        "platform": record.platform,
        "formatted_output_id": record.formatted_output_id,
        "status": record.status,
        "remote_id": record.remote_id,
        "url": record.url,
        "published_at": _dt(record.published_at),
        "error": record.error,
        "attempt": record.attempt,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def history_payload(item: PublishStatusHistory) -> dict:
    return {
        "id": item.id,
        "status": item.status,
        "source": item.source,
        "created_at": _dt(item.created_at),
    }


def metric_payload(snapshot: MetricSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "publish_record_id": snapshot.publish_record_id,
        "platform": snapshot.platform,
        "views": snapshot.views,
        "likes": snapshot.likes,
        "comments": snapshot.comments,
        "shares": snapshot.shares,
        "revenue_cents": snapshot.revenue_cents,
        "revenue_yuan": round(snapshot.revenue_cents / 100.0, 2),
        "source": snapshot.source,
        "captured_at": _dt(snapshot.captured_at),
    }


def skill_detail_payload(skill: Skill, info=None) -> dict:
    payload = skill_payload(skill)
    payload["standard_name"] = info.standard_name if info is not None else skill.slug
    payload["resources"] = list(info.resources) if info is not None else []
    payload["entry"] = info.entry if info is not None else "SKILL.md"
    payload["license"] = info.license if info is not None else ""
    payload["compatibility"] = info.compatibility if info is not None else ""
    payload["allowed_tools"] = list(info.allowed_tools) if info is not None else []
    return payload


def skill_payload(skill: Skill) -> dict:
    return {
        "id": skill.id,
        "slug": skill.slug,
        "name": skill.name,
        "version": skill.version,
        "description": skill.description,
        "applies_to": list(skill.applies_to or []),
        "enabled": skill.enabled,
        "source_path": skill.source_path,
        "status": skill.status,
        "error": skill.error,
        "updated_at": _dt(skill.updated_at),
    }


def binding_payload(binding: SkillBinding, skill: Skill | None = None) -> dict:
    return {
        "id": binding.id,
        "stage": binding.stage,
        "skill_id": binding.skill_id,
        "order": binding.order,
        "enabled": binding.enabled,
        "skill": skill_payload(skill) if skill is not None else None,
    }


def model_payload(profile: ModelProfile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "api_key_env": profile.api_key_env,
        "model": profile.model,
        "input_price_per_1k": profile.input_price_per_1k,
        "output_price_per_1k": profile.output_price_per_1k,
        "currency": profile.currency,
        "context_window": profile.context_window,
        "enabled": profile.enabled,
        "updated_at": _dt(profile.updated_at),
    }


def model_binding_payload(binding: StageModelBinding, profile: ModelProfile | None = None) -> dict:
    return {
        "id": binding.id,
        "stage": binding.stage,
        "model_profile_id": binding.model_profile_id,
        "temperature": binding.temperature,
        "max_tokens": binding.max_tokens,
        "profile": model_payload(profile) if profile is not None else None,
        "updated_at": _dt(binding.updated_at),
    }


def suggestion_payload(suggestion: EvolutionSuggestion) -> dict:
    return {
        "id": suggestion.id,
        "type": suggestion.type,
        "target_stage": suggestion.target_stage,
        "title": suggestion.title,
        "rationale": suggestion.rationale,
        "evidence": suggestion.evidence,
        "patch": suggestion.patch,
        "expected_impact": suggestion.expected_impact,
        "status": suggestion.status,
        "before_snapshot": suggestion.before_snapshot,
        "after_snapshot": suggestion.after_snapshot,
        "baseline": suggestion.baseline,
        "result": suggestion.result,
        "decided_note": suggestion.decided_note,
        "created_at": _dt(suggestion.created_at),
        "decided_at": _dt(suggestion.decided_at),
        "applied_at": _dt(suggestion.applied_at),
    }


def llm_call_payload(call: LLMCall) -> dict:
    return {
        "id": call.id,
        "article_id": call.article_id,
        "run_id": call.run_id,
        "stage": call.stage,
        "provider": call.provider,
        "model": call.model,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
        "cost": call.cost,
        "currency": call.currency,
        "latency_ms": call.latency_ms,
        "status": call.status,
        "estimated": call.estimated,
        "price_missing": call.price_missing,
        "created_at": _dt(call.created_at),
    }


def dump_list(items: list[Any], serializer) -> list[dict]:
    return [serializer(item) for item in items]
