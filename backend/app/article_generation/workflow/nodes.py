"""Workflow node implementations with stage tracking and failure isolation.

Each node owns at most one LangGraph interrupt: the ``pause`` node pauses the
run between stages, and the ``publish`` node asks for confirmation. Keeping
them in separate nodes means resume values are replayed deterministically when
a suspended node restarts from the beginning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from langgraph.types import interrupt
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.article_generation.formatting.service import FormattingService
from app.article_generation.outline.service import OutlineService
from app.article_generation.publishing.service import PublishingService
from app.article_generation.research.service import ResearchService
from app.article_generation.review.decision import RejectionRouter
from app.article_generation.review.service import ReviewService, latest_failed_issues
from app.article_generation.title_optimization.service import TitleOptimizationService
from app.article_generation.workflow.state import ArticleState
from app.article_generation.writing.service import WritingService
from app.core.config import Settings, get_settings
from app.core.constants import (
    ArticleStatus,
    RunStatus,
    STAGE_LABELS,
    Stage,
    StageStatus,
)
from app.core.events import Event, event_bus
from app.core.llm import LLMService
from app.core.llm_context import llm_context
from app.core.security import CredentialService
from app.core.tracing import trace_span
from app.models.article import (
    Article,
    ReviewDecision,
    ReviewReport,
    StageRun,
    WorkflowRun,
)
from app.models.llm import LLMCall
from app.models.system import Setting
from app.platforms.registry import PlatformRegistry
from app.skills.manager import SkillManager
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

ROLLBACK_NODES = {
    Stage.RESEARCH: "research",
    Stage.OUTLINE: "outline",
    Stage.WRITING: "write",
}


@dataclass
class WorkflowContext:
    session_factory: sessionmaker[Session]
    llm: LLMService
    registry: PlatformRegistry
    skill_registry: SkillRegistry
    settings: Settings | None = None
    search_tool: Any = None

    def __post_init__(self) -> None:
        if self.settings is None:
            self.settings = get_settings()


class WorkflowNodes:
    def __init__(self, context: WorkflowContext) -> None:
        self.ctx = context

    # ---------- stage bookkeeping ----------

    def _article_and_run(
        self, session: Session, state: ArticleState
    ) -> tuple[Article, WorkflowRun]:
        article = session.get(Article, state["article_id"])
        run = session.get(WorkflowRun, state["run_id"])
        if article is None or run is None:
            raise RuntimeError("工作流上下文缺失")
        return article, run

    def _begin(self, state: ArticleState, stage: str) -> tuple[str, int]:
        with self.ctx.session_factory() as session:
            article, run = self._article_and_run(session, state)
            stage_run = session.scalar(
                select(StageRun)
                .where(
                    StageRun.run_id == run.id,
                    StageRun.stage == stage,
                    StageRun.status == StageStatus.PENDING,
                )
                .order_by(StageRun.attempt.desc())
            )
            if stage_run is None:
                current_attempt = session.scalar(
                    select(func.max(StageRun.attempt)).where(
                        StageRun.run_id == run.id, StageRun.stage == stage
                    )
                )
                stage_run = StageRun(
                    run_id=run.id,
                    article_id=article.id,
                    stage=stage,
                    attempt=int(current_attempt or 0) + 1,
                )
                session.add(stage_run)
            stage_run.status = StageStatus.RUNNING
            stage_run.started_at = datetime.now(UTC)
            stage_run.finished_at = None
            stage_run.error = None
            run.status = RunStatus.RUNNING
            run.current_stage = stage
            run.error = None
            article.status = ArticleStatus.RUNNING
            article.current_stage = stage
            session.commit()
            stage_run_id = stage_run.id
            attempt = int(stage_run.attempt)
        self._emit(
            state,
            "stage.status",
            {"stage": stage, "label": STAGE_LABELS.get(stage, stage), "status": "running"},
        )
        return stage_run_id, attempt

    def _finish(
        self,
        state: ArticleState,
        stage: str,
        stage_run_id: str,
        *,
        error: str | None = None,
        artifact: str | None = None,
    ) -> dict:
        with self.ctx.session_factory() as session:
            article, run = self._article_and_run(session, state)
            stage_run = session.get(StageRun, stage_run_id)
            if stage_run is not None:
                stage_run.status = StageStatus.FAILED if error else StageStatus.COMPLETED
                stage_run.finished_at = datetime.now(UTC)
                stage_run.error = error
                if stage_run.started_at is not None and not error:
                    totals = session.execute(
                        select(
                            func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                            func.coalesce(func.sum(LLMCall.completion_tokens), 0),
                            func.sum(LLMCall.cost),
                        ).where(
                            LLMCall.run_id == run.id,
                            LLMCall.stage == stage,
                            LLMCall.created_at >= stage_run.started_at,
                        )
                    ).one()
                    stage_run.prompt_tokens = int(totals[0] or 0)
                    stage_run.completion_tokens = int(totals[1] or 0)
                    stage_run.cost = None if totals[2] is None else float(totals[2])
            if error:
                run.error = error
                article.error = error
                article.status = ArticleStatus.FAILED
            session.commit()
        self._emit(
            state,
            "stage.status",
            {
                "stage": stage,
                "label": STAGE_LABELS.get(stage, stage),
                "status": "failed" if error else "completed",
                "error": error,
            },
        )
        if artifact and not error:
            self._emit(state, "artifact.created", {"stage": stage, "artifact": artifact})
        return {"stage_error": error} if error else {"stage_error": None}

    def _emit(self, state: ArticleState, event_type: str, data: dict) -> None:
        event_bus.publish(
            Event(
                type=event_type,
                article_id=state.get("article_id"),
                run_id=state.get("run_id"),
                data=data,
            )
        )

    def _pause_requested(self, state: ArticleState) -> bool:
        with self.ctx.session_factory() as session:
            run = session.get(WorkflowRun, state["run_id"])
            return bool(run and run.pause_requested)

    def _auto_review_advance(self) -> bool:
        """Whether a passing review may continue to formatting automatically."""
        with self.ctx.session_factory() as session:
            row = session.get(Setting, "auto_review_advance")
        value = row.value if row is not None else False
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _llm_context(self, state: ArticleState, stage: str):
        return llm_context(
            article_id=state["article_id"], run_id=state["run_id"], stage=stage
        )

    def _execute(
        self,
        state: ArticleState,
        stage: str,
        callback: Callable[[Session], tuple[str, dict]],
        *,
        next_node: str | None = None,
    ) -> dict:
        stage_run_id, attempt = self._begin(state, stage)
        stage_name = str(stage)
        metadata = {
            "article_id": state["article_id"],
            "run_id": state["run_id"],
            "stage": stage_name,
            "attempt": attempt,
        }
        with trace_span(
            f"stage.{stage_name}",
            input={
                "article_id": state["article_id"],
                "run_id": state["run_id"],
                "attempt": attempt,
            },
            metadata=metadata,
        ) as span:
            try:
                with self.ctx.session_factory() as session:
                    artifact, updates = callback(session)
                result = self._finish(state, stage, stage_run_id, artifact=artifact)
                result.update(updates)
                if next_node and not result.get("stage_error") and self._pause_requested(state):
                    result.update({"pause_requested": True, "next_node": next_node})
                if span is not None:
                    span.update(output={"stage": stage_name, "artifact": artifact})
                return result
            except Exception as exc:  # noqa: BLE001 - record and stop the graph
                logger.exception("stage %s failed for run %s", stage, state.get("run_id"))
                result = self._finish(state, stage, stage_run_id, error=str(exc))
                if span is not None:
                    span.update(
                        output={"stage": stage_name, "error": str(exc)},
                        level="ERROR",
                        status_message=str(exc),
                    )
                return result

    # ---------- stage nodes ----------

    def topic(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            article = session.get(Article, state["article_id"])
            if article is None:
                raise RuntimeError("文章不存在")
            if not article.current_topic_id:
                raise RuntimeError("请先选择一个选题后再启动工作流")
            return "topic", {}

        return self._execute(state, Stage.TOPIC, callback, next_node="research")

    def _deep_research_runner(self):
        settings = self.ctx.settings
        if settings is None or not settings.deep_research_enabled:
            return None
        from app.article_generation.research.deep_agent import DeepResearchRunner
        from app.article_generation.research.tools import HttpSearchTool

        return DeepResearchRunner(
            self.ctx.llm,
            self.ctx.search_tool or HttpSearchTool(),
            max_steps=settings.deep_research_max_steps,
            timeout_seconds=settings.deep_research_timeout_seconds,
            max_tokens=settings.deep_research_max_tokens,
        )

    def research(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            service = ResearchService(
                session,
                self.ctx.llm,
                search_tool=self.ctx.search_tool,
                deep_agent=self._deep_research_runner(),
                skills=SkillManager(session, self.ctx.skill_registry),
                feedback=state.get("human_feedback"),
            )
            with self._llm_context(state, Stage.RESEARCH):
                result = service.run(state["article_id"])
            return "research", {"research_low_confidence": result.low_confidence}

        return self._execute(state, Stage.RESEARCH, callback, next_node="outline")

    def outline(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            feedback = str(state.get("human_feedback") or "").strip()
            service = OutlineService(
                session,
                self.ctx.llm,
                skills=SkillManager(session, self.ctx.skill_registry),
                feedback=feedback,
            )
            human_rejection = (
                state.get("review_human_decision") == "reject"
                and state.get("review_rejection_target") == Stage.OUTLINE
            )
            targeted = human_rejection or (
                state.get("review_verdict") == "fail"
                and state.get("rollback_target") == Stage.OUTLINE
            )
            with self._llm_context(state, Stage.OUTLINE):
                if targeted:
                    if human_rejection:
                        issues = [f"人工驳回意见：{feedback}"]
                    else:
                        issues = [
                            f"{item.get('location') or '整体结构'}：{item.get('description', '')}"
                            for item in latest_failed_issues(session, state["article_id"])
                        ]
                    version = service.revise(
                        state["article_id"], issues or ["审核认为结构需要调整"]
                    )
                else:
                    version = service.generate(state["article_id"])
            return "outline", {"outline_version": version.version}

        return self._execute(state, Stage.OUTLINE, callback, next_node="write")

    def write(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            skills = SkillManager(session, self.ctx.skill_registry)
            feedback = str(state.get("human_feedback") or "").strip()
            service = WritingService(
                session, self.ctx.llm, skills, feedback=feedback
            )
            human_rejection = (
                state.get("review_human_decision") == "reject"
                and state.get("review_rejection_target") == Stage.WRITING
            )
            targeted = (
                state.get("review_verdict") == "fail"
                and state.get("rollback_target") == Stage.WRITING
            )
            with self._llm_context(state, Stage.WRITING):
                if human_rejection:
                    result = service.revise(
                        state["article_id"], [f"人工驳回意见：{feedback}"]
                    )
                elif targeted:
                    result = service.revise_targeted(state["article_id"])
                else:
                    result = service.generate(state["article_id"])
            return "draft", {"draft_version": result.draft.version}

        return self._execute(state, Stage.WRITING, callback, next_node="title")

    def title(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            service = TitleOptimizationService(
                session,
                self.ctx.llm,
                skills=SkillManager(session, self.ctx.skill_registry),
            )
            with self._llm_context(state, Stage.TITLE):
                result = service.optimize(state["article_id"])
            return "title", {"title_version": result.title_version.version}

        return self._execute(state, Stage.TITLE, callback, next_node="review")

    def review(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            service = ReviewService(
                session,
                self.ctx.llm,
                skills=SkillManager(session, self.ctx.skill_registry),
            )
            with self._llm_context(state, Stage.REVIEW):
                result = service.review(state["article_id"])
            article, run = self._article_and_run(session, state)
            updates: dict = {
                "review_verdict": result.verdict,
                "rollback_target": result.rollback_to,
            }
            if result.verdict == "fail":
                run.revision_count += 1
                updates["revision_count"] = run.revision_count
                if run.revision_count < run.max_revisions and result.rollback_to:
                    self._reset_downstream(session, article.id, run.id, result.rollback_to)
            session.commit()
            return "review", updates

        result = self._execute(state, Stage.REVIEW, callback)
        if result.get("stage_error"):
            return result
        auto_advance = self._auto_review_advance()
        result["review_human_required"] = not auto_advance
        if self._pause_requested(state):
            if not auto_advance:
                next_node = "review_decision"
            elif result.get("review_verdict") == "pass":
                next_node = "format"
            else:
                rollback_to = result.get("rollback_target") or Stage.WRITING
                next_node = ROLLBACK_NODES.get(rollback_to, "write")
            result.update({"pause_requested": True, "next_node": next_node})
        with self.ctx.session_factory() as session:
            run = session.get(WorkflowRun, state["run_id"])
            event_bus.publish(
                Event(
                    type="review.completed",
                    article_id=state.get("article_id"),
                    run_id=state.get("run_id"),
                    data={
                        "verdict": result.get("review_verdict"),
                        "rollback_to": result.get("rollback_target"),
                        "revision_count": run.revision_count if run else None,
                        "auto_advance": auto_advance,
                    },
                )
            )
        return result

    def review_decision(self, state: ArticleState) -> dict:
        """Human gate after review: approve to formatting or reject with routing."""
        with self.ctx.session_factory() as session:
            article, run = self._article_and_run(session, state)
            run.status = RunStatus.WAITING_REVIEW
            run.current_stage = Stage.REVIEW
            article.status = ArticleStatus.WAITING_REVIEW
            article.current_stage = Stage.REVIEW
            session.commit()
        self._emit(state, "run.status", {"status": RunStatus.WAITING_REVIEW})
        self._emit(
            state,
            "review.waiting",
            {
                "verdict": state.get("review_verdict"),
                "rollback_to": state.get("rollback_target"),
                "revision_count": state.get("revision_count"),
            },
        )
        decision = interrupt(
            {
                "type": "review_decision",
                "run_id": state["run_id"],
                "verdict": state.get("review_verdict"),
                "rollback_to": state.get("rollback_target"),
                "revision_count": state.get("revision_count"),
            }
        )
        payload = decision if isinstance(decision, dict) else {}
        action = str(payload.get("decision") or "").lower()
        feedback = str(payload.get("feedback") or "").strip()

        with self.ctx.session_factory() as session:
            article, run = self._article_and_run(session, state)
            report = session.scalar(
                select(ReviewReport)
                .where(ReviewReport.article_id == article.id)
                .order_by(ReviewReport.created_at.desc())
            )
            if action == "reject":
                if not feedback:
                    raise ValueError("驳回意见不能为空")
                target, reason = RejectionRouter(
                    self.ctx.llm
                ).route(
                    article_id=article.id,
                    title=article.title,
                    feedback=feedback,
                    verdict=state.get("review_verdict"),
                    rationale=report.rationale if report is not None else "",
                )
                session.add(
                    ReviewDecision(
                        article_id=article.id,
                        run_id=run.id,
                        report_id=report.id if report is not None else None,
                        decision="rejected",
                        feedback=feedback,
                        rollback_to=target,
                        target_reason=reason,
                    )
                )
                self._reset_downstream(session, article.id, run.id, target)
                updates = {
                    "review_human_decision": "reject",
                    "review_human_required": False,
                    "review_rejection_target": target,
                    "rollback_target": target,
                    "human_feedback": feedback,
                }
            else:
                session.add(
                    ReviewDecision(
                        article_id=article.id,
                        run_id=run.id,
                        report_id=report.id if report is not None else None,
                        decision="approved",
                        feedback=feedback,
                        target_reason="人工通过",
                    )
                )
                updates = {
                    "review_human_decision": "approve",
                    "review_human_required": False,
                    "human_feedback": None,
                }
            run.status = RunStatus.RUNNING
            article.status = ArticleStatus.RUNNING
            session.commit()

        self._emit(state, "run.status", {"status": RunStatus.RUNNING})
        self._emit(
            state,
            "review.decided",
            {
                "decision": updates["review_human_decision"],
                "rollback_to": updates.get("review_rejection_target"),
                "feedback": feedback,
            },
        )
        return updates

    @staticmethod
    def _reset_downstream(
        session: Session, article_id: str, run_id: str, rollback_to: str
    ) -> None:
        order = [
            Stage.RESEARCH,
            Stage.OUTLINE,
            Stage.WRITING,
            Stage.TITLE,
            Stage.REVIEW,
            Stage.FORMATTING,
            Stage.PUBLISHING,
        ]
        if rollback_to not in order:
            return
        start = order.index(rollback_to) + 1
        for stage in order[start:]:
            pending = session.scalar(
                select(StageRun).where(
                    StageRun.run_id == run_id,
                    StageRun.stage == stage,
                    StageRun.status == StageStatus.PENDING,
                )
            )
            if pending is not None:
                continue
            current = session.scalar(
                select(func.max(StageRun.attempt)).where(
                    StageRun.run_id == run_id, StageRun.stage == stage
                )
            )
            session.add(
                StageRun(
                    run_id=run_id,
                    article_id=article_id,
                    stage=stage,
                    attempt=int(current or 0) + 1,
                    status=StageStatus.PENDING,
                )
            )

    def format(self, state: ArticleState) -> dict:
        def callback(session: Session) -> tuple[str, dict]:
            service = FormattingService(
                session, self.ctx.registry, CredentialService(session), llm=self.ctx.llm
            )
            batch = service.format_article(state["article_id"])
            ready = [output for output in batch.outputs if output.status == "ready"]
            if not ready:
                raise RuntimeError("所有平台排版均失败")
            return "format", {
                "formatted_platforms": [output.platform for output in ready]
            }

        return self._execute(state, Stage.FORMATTING, callback, next_node="publish")

    def publish(self, state: ArticleState) -> dict:
        with self.ctx.session_factory() as session:
            article = session.get(Article, state["article_id"])
            needs_confirmation = bool(article and article.publish_confirmation)
            summary = (
                PublishingService(
                    session, self.ctx.registry, CredentialService(session)
                ).confirm_summary(article.id)
                if article
                else {}
            )
        if needs_confirmation:
            decision = interrupt(
                {
                    "type": "publish_confirmation",
                    "run_id": state["run_id"],
                    "summary": summary,
                }
            )
            if decision != "approve":
                with self.ctx.session_factory() as session:
                    article = session.get(Article, state["article_id"])
                    run = session.get(WorkflowRun, state["run_id"])
                    if article is not None:
                        article.status = ArticleStatus.WAITING_PUBLISH
                    if run is not None:
                        run.status = RunStatus.WAITING_PUBLISH
                    session.commit()
                self._emit(
                    state, "publish.updated", {"status": "cancelled", "platforms": []}
                )
                return {"publish_result": "cancelled"}

        def callback(session: Session) -> tuple[str, dict]:
            service = PublishingService(
                session, self.ctx.registry, CredentialService(session)
            )
            result = service.publish(state["article_id"])
            if not result.records:
                raise RuntimeError("没有可发布的平台")
            platforms = [
                {"platform": record.platform, "status": record.status, "url": record.url}
                for record in result.records
            ]
            self._emit(
                state, "publish.updated", {"status": "done", "platforms": platforms}
            )
            fully_published = all(
                record.status == "published" for record in result.records
            )
            return "publish", {
                "publish_result": "published" if fully_published else "partial"
            }

        return self._execute(state, Stage.PUBLISHING, callback)

    # ---------- control nodes ----------

    def pause(self, state: ArticleState) -> dict:
        with self.ctx.session_factory() as session:
            run = session.get(WorkflowRun, state["run_id"])
            article = session.get(Article, state["article_id"])
            if run is not None:
                run.pause_requested = False
                run.status = RunStatus.PAUSED
            if article is not None:
                article.status = ArticleStatus.PAUSED
            session.commit()
        self._emit(
            state,
            "run.status",
            {"status": "paused", "next_node": state.get("next_node")},
        )
        interrupt({"type": "pause", "run_id": state["run_id"]})
        with self.ctx.session_factory() as session:
            run = session.get(WorkflowRun, state["run_id"])
            article = session.get(Article, state["article_id"])
            if run is not None:
                run.status = RunStatus.RUNNING
            if article is not None:
                article.status = ArticleStatus.RUNNING
            session.commit()
        self._emit(state, "run.status", {"status": "resumed"})
        return {"pause_requested": False}

    def halt(self, state: ArticleState) -> dict:
        with self.ctx.session_factory() as session:
            article, run = self._article_and_run(session, state)
            if state.get("stage_error"):
                run.status = RunStatus.FAILED
                article.status = ArticleStatus.FAILED
                article.error = state.get("stage_error")
            else:
                run.status = RunStatus.NEEDS_HUMAN
                article.status = ArticleStatus.NEEDS_HUMAN
                article.error = "自动返工次数已达上限，需要人工处理"
            session.commit()
        self._emit(state, "run.status", {"status": "finished", "halted": True})
        return {}
