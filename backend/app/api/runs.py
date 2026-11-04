"""Workflow run control endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.articles import get_article
from app.api.deps import RunnerDep, SessionDep
from app.api.schemas import ConfirmPublish, ReviewDecisionRequest
from app.api.serializers import run_payload
from app.core.constants import RunStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.article import WorkflowRun

router = APIRouter(tags=["runs"])


@router.post("/articles/{article_id}/run", status_code=202)
async def start_run(article_id: str, session: Session = SessionDep, runner=RunnerDep) -> dict:
    # This route must stay async: the runner schedules the graph on the
    # current event loop, and sync routes execute in a worker thread where no
    # loop exists (the run would be created but never executed).
    get_article(session, article_id)
    run = runner.start_run(article_id)
    return run_payload(run)


@router.get("/articles/{article_id}/runs")
def list_runs(article_id: str, session: Session = SessionDep) -> dict:
    get_article(session, article_id)
    runs = list(
        session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.article_id == article_id)
            .order_by(WorkflowRun.created_at.desc())
        )
    )
    return {"items": [run_payload(item) for item in runs]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = SessionDep) -> dict:
    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError("工作流运行不存在")
    return run_payload(run)


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str, runner=RunnerDep) -> dict:
    return run_payload(runner.request_pause(run_id))


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: str, runner=RunnerDep) -> dict:
    return run_payload(runner.resume_run(run_id))


@router.post("/articles/{article_id}/review/decision")
async def decide_review(
    article_id: str,
    payload: ReviewDecisionRequest,
    session: Session = SessionDep,
    runner=RunnerDep,
) -> dict:
    get_article(session, article_id)
    feedback = payload.feedback.strip()
    if payload.decision == "reject" and not feedback:
        raise ValidationError("驳回需要填写意见")
    run = session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.article_id == article_id,
            WorkflowRun.status == RunStatus.WAITING_REVIEW,
        )
        .order_by(WorkflowRun.created_at.desc())
    )
    if run is None:
        raise ConflictError("当前没有等待审稿确认的工作流")
    return run_payload(
        runner.resume_run(
            run.id, decision={"decision": payload.decision, "feedback": feedback}
        )
    )


@router.post("/articles/{article_id}/confirm-publish")
async def confirm_publish(
    article_id: str,
    payload: ConfirmPublish,
    session: Session = SessionDep,
    runner=RunnerDep,
) -> dict:
    get_article(session, article_id)
    run = session.scalar(
        select(WorkflowRun)
        .where(
            WorkflowRun.article_id == article_id,
            WorkflowRun.status == RunStatus.WAITING_PUBLISH,
        )
        .order_by(WorkflowRun.created_at.desc())
    )
    if run is None:
        raise ConflictError("当前没有等待发布确认的工作流")
    return run_payload(runner.resume_run(run.id, decision=payload.decision))
