"""Stage timeline and per-stage content endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.articles import get_article
from app.api.deps import LLMDep, SessionDep, SkillsDep
from app.api.schemas import DraftEdit, OutlineEdit, TitleEdit
from app.api.serializers import (
    draft_payload,
    fact_payload,
    format_payload,
    history_payload,
    metric_payload,
    outline_payload,
    publish_payload,
    review_decision_payload,
    review_payload,
    run_payload,
    source_payload,
    stage_run_payload,
    title_payload,
    topic_payload,
)
from app.article_generation.outline.service import OutlineService
from app.article_generation.title_optimization.service import TitleOptimizationService
from app.article_generation.writing.service import WritingService
from app.core.constants import STAGE_LABELS, STAGE_ORDER, Stage
from app.core.errors import NotFoundError, ValidationError
from app.models.article import (
    DraftVersion,
    Fact,
    FormattedOutput,
    MetricSnapshot,
    OutlineVersion,
    PublishRecord,
    ReviewDecision,
    ReviewReport,
    Source,
    StageRun,
    TitleVersion,
    Topic,
    WorkflowRun,
)
from app.skills.manager import SkillManager

router = APIRouter(prefix="/articles/{article_id}/stages", tags=["stages"])


@router.get("")
def stage_timeline(article_id: str, session: Session = SessionDep) -> dict:
    article = get_article(session, article_id)
    run = session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.article_id == article_id)
        .order_by(WorkflowRun.created_at.desc())
    )
    runs = []
    if run is not None:
        runs = list(
            session.scalars(
                select(StageRun)
                .where(StageRun.run_id == run.id)
                .order_by(StageRun.attempt)
            )
        )
    latest_by_stage: dict[str, StageRun] = {}
    for item in runs:
        latest_by_stage[item.stage] = item
    stages = []
    for stage in STAGE_ORDER:
        item = latest_by_stage.get(stage)
        stages.append(
            {
                "stage": stage,
                "label": STAGE_LABELS.get(stage, stage),
                "status": item.status if item else "pending",
                "attempt": item.attempt if item else 0,
                "started_at": item.started_at.isoformat() if item and item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item and item.finished_at else None,
                "error": item.error if item else None,
                "artifact": _artifact_summary(session, article_id, stage),
            }
        )
    return {
        "article": {
            "id": article.id,
            "status": article.status,
            "current_stage": article.current_stage,
        },
        "run": run_payload(run) if run is not None else None,
        "stages": stages,
    }


@router.get("/{stage}")
def stage_detail(article_id: str, stage: str, session: Session = SessionDep) -> dict:
    get_article(session, article_id)
    if stage not in STAGE_ORDER:
        raise ValidationError(f"未知阶段: {stage}")
    run = session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.article_id == article_id)
        .order_by(WorkflowRun.created_at.desc())
    )
    stage_run = None
    if run is not None:
        stage_run = session.scalar(
            select(StageRun)
            .where(StageRun.run_id == run.id, StageRun.stage == stage)
            .order_by(StageRun.attempt.desc())
        )
    return {
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage),
        "stage_run": stage_run_payload(stage_run) if stage_run else None,
        "content": _stage_content(session, article_id, stage),
    }


@router.put("/outline")
def edit_outline(article_id: str, payload: OutlineEdit, session: Session = SessionDep, llm=LLMDep) -> dict:
    get_article(session, article_id)
    outline = OutlineService(session, llm).edit(article_id, payload.content, note=payload.note)
    return outline_payload(outline)


@router.put("/writing")
def edit_draft(
    article_id: str,
    payload: DraftEdit,
    session: Session = SessionDep,
    llm=LLMDep,
    skills=SkillsDep,
) -> dict:
    get_article(session, article_id)
    service = WritingService(session, llm, SkillManager(session, skills))
    draft = service.user_edit(
        article_id,
        content_md=payload.content_md,
        summary=payload.summary,
        title=payload.title,
    )
    return draft_payload(draft)


@router.put("/title_optimization")
def edit_title(
    article_id: str,
    payload: TitleEdit,
    session: Session = SessionDep,
    llm=LLMDep,
) -> dict:
    get_article(session, article_id)
    version = TitleOptimizationService(session, llm).select(
        article_id, payload.title, note=payload.note
    )
    return title_payload(version)


def _artifact_summary(session: Session, article_id: str, stage: str) -> dict:
    if stage == Stage.TOPIC:
        article = get_article(session, article_id)
        return {"count": 1 if article.current_topic_id else 0}
    if stage == Stage.RESEARCH:
        sources = session.scalar(
            select(Source).where(Source.article_id == article_id).limit(1)
        )
        facts = session.scalar(select(Fact).where(Fact.article_id == article_id).limit(1))
        return {"sources": sources is not None, "facts": facts is not None}
    if stage == Stage.OUTLINE:
        outline = session.scalar(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        )
        return {"version": outline.version if outline else None}
    if stage == Stage.WRITING:
        draft = session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )
        return {"version": draft.version if draft else None, "word_count": draft.word_count if draft else 0}
    if stage == Stage.TITLE:
        version = session.scalar(
            select(TitleVersion)
            .where(TitleVersion.article_id == article_id)
            .order_by(TitleVersion.version.desc())
        )
        return {
            "version": version.version if version else None,
            "selected_title": version.selected_title if version else None,
            "candidate_count": len(version.candidates or []) if version else 0,
        }
    if stage == Stage.REVIEW:
        report = session.scalar(
            select(ReviewReport)
            .where(ReviewReport.article_id == article_id)
            .order_by(ReviewReport.created_at.desc())
        )
        return {
            "verdict": report.verdict if report else None,
            "total": report.total if report else None,
        }
    if stage == Stage.FORMATTING:
        outputs = list(
            session.scalars(
                select(FormattedOutput).where(FormattedOutput.article_id == article_id)
            )
        )
        return {
            "platforms": [item.platform for item in outputs],
            "ready": [item.platform for item in outputs if item.status == "ready"],
        }
    if stage == Stage.PUBLISHING:
        records = list(
            session.scalars(
                select(PublishRecord).where(PublishRecord.article_id == article_id)
            )
        )
        return {
            "platforms": [item.platform for item in records],
            "published": [item.platform for item in records if item.status == "published"],
        }
    return {}


def _stage_content(session: Session, article_id: str, stage: str) -> dict:
    if stage == Stage.TOPIC:
        article = get_article(session, article_id)
        selected = (
            session.get(Topic, article.current_topic_id) if article.current_topic_id else None
        )
        topics = list(
            session.scalars(
                select(Topic).where(Topic.article_id == article_id).order_by(Topic.created_at)
            )
        )
        return {
            "selected": topic_payload(selected) if selected else None,
            "topics": [topic_payload(item) for item in topics],
        }
    if stage == Stage.RESEARCH:
        sources = list(
            session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        facts = list(session.scalars(select(Fact).where(Fact.article_id == article_id)))
        return {
            "sources": [source_payload(item) for item in sources],
            "facts": [fact_payload(item) for item in facts],
        }
    if stage == Stage.OUTLINE:
        history = list(
            session.scalars(
                select(OutlineVersion)
                .where(OutlineVersion.article_id == article_id)
                .order_by(OutlineVersion.version.desc())
            )
        )
        return {
            "latest": outline_payload(history[0]) if history else None,
            "history": [outline_payload(item) for item in history],
        }
    if stage == Stage.WRITING:
        history = list(
            session.scalars(
                select(DraftVersion)
                .where(DraftVersion.article_id == article_id)
                .order_by(DraftVersion.version.desc())
            )
        )
        return {
            "latest": draft_payload(history[0]) if history else None,
            "history": [draft_payload(item) for item in history],
        }
    if stage == Stage.TITLE:
        history = list(
            session.scalars(
                select(TitleVersion)
                .where(TitleVersion.article_id == article_id)
                .order_by(TitleVersion.version.desc())
            )
        )
        return {
            "latest": title_payload(history[0]) if history else None,
            "history": [title_payload(item) for item in history],
        }
    if stage == Stage.REVIEW:
        history = list(
            session.scalars(
                select(ReviewReport)
                .where(ReviewReport.article_id == article_id)
                .order_by(ReviewReport.created_at.desc())
            )
        )
        decision = session.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.article_id == article_id)
            .order_by(ReviewDecision.created_at.desc())
        )
        return {
            "latest": review_payload(history[0]) if history else None,
            "history": [review_payload(item) for item in history],
            "latest_decision": review_decision_payload(decision) if decision else None,
        }
    if stage == Stage.FORMATTING:
        outputs = list(
            session.scalars(
                select(FormattedOutput)
                .where(FormattedOutput.article_id == article_id)
                .order_by(FormattedOutput.platform)
            )
        )
        return {"outputs": [format_payload(item) for item in outputs]}
    if stage == Stage.PUBLISHING:
        records = list(
            session.scalars(
                select(PublishRecord)
                .where(PublishRecord.article_id == article_id)
                .order_by(PublishRecord.platform)
            )
        )
        payload = []
        for record in records:
            item = publish_payload(record)
            metrics = list(
                session.scalars(
                    select(MetricSnapshot)
                    .where(MetricSnapshot.publish_record_id == record.id)
                    .order_by(MetricSnapshot.captured_at.desc())
                    .limit(1)
                )
            )
            item["latest_metric"] = metric_payload(metrics[0]) if metrics else None
            item["history"] = _history(session, record.id)
            payload.append(item)
        return {"records": payload}
    raise NotFoundError(f"未知阶段: {stage}")


def _history(session: Session, record_id: str) -> list[dict]:
    from app.models.article import PublishStatusHistory

    rows = session.scalars(
        select(PublishStatusHistory)
        .where(PublishStatusHistory.publish_record_id == record_id)
        .order_by(PublishStatusHistory.created_at)
    )
    return [history_payload(item) for item in rows]
