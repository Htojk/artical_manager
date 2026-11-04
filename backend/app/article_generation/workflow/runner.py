"""Background workflow runner: scheduling, checkpoints, pause and resume."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.article_generation.workflow.graph import build_graph
from app.article_generation.workflow.nodes import WorkflowContext, WorkflowNodes
from app.core.config import Settings, get_settings
from app.core.constants import ArticleStatus, RunStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.events import Event, event_bus
from app.core.llm import LLMService
from app.core.tracing import trace_attributes, trace_span
from app.models.article import Article, WorkflowRun
from app.models.base import new_id
from app.platforms.registry import PlatformRegistry
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.PAUSED,
    RunStatus.WAITING_REVIEW,
    RunStatus.WAITING_PUBLISH,
}


class WorkflowRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        llm: LLMService,
        registry: PlatformRegistry,
        skill_registry: SkillRegistry,
        *,
        settings: Settings | None = None,
        search_tool: Any = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.context = WorkflowContext(
            session_factory=session_factory,
            llm=llm,
            registry=registry,
            skill_registry=skill_registry,
            settings=self.settings,
            search_tool=search_tool,
        )
        self.nodes = WorkflowNodes(self.context)
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task] = set()
        self._lock = threading.Lock()

    # ---------- lifecycle ----------

    def start_run(self, article_id: str) -> WorkflowRun:
        with self.session_factory() as session:
            article = session.get(Article, article_id)
            if article is None:
                raise NotFoundError(f"文章不存在: {article_id}")
            if not article.current_topic_id:
                raise ValidationError("请先选择一个选题后再启动工作流")
            active = session.scalar(
                select(WorkflowRun)
                .where(
                    WorkflowRun.article_id == article_id,
                    WorkflowRun.status.in_(ACTIVE_STATUSES),
                )
                .order_by(WorkflowRun.created_at.desc())
            )
            if active is not None:
                raise ConflictError(
                    "该文章已有进行中的工作流",
                    details={"run_id": active.id, "status": active.status},
                )
            run_id = new_id()
            run = WorkflowRun(
                id=run_id,
                article_id=article_id,
                thread_id=run_id,
                status=RunStatus.PENDING,
                max_revisions=self.settings.max_revisions,
            )
            session.add(run)
            article.status = ArticleStatus.RUNNING
            article.current_stage = "topic_selection"
            article.error = None
            session.commit()
            run_id = run.id
        self._emit("run.status", article_id, run_id, {"status": "pending"})
        self._schedule(run_id, initial=True)
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> WorkflowRun:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise NotFoundError(f"工作流运行不存在: {run_id}")
            session.expunge(run)
            return run

    def request_pause(self, run_id: str) -> WorkflowRun:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise NotFoundError(f"工作流运行不存在: {run_id}")
            if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                raise ConflictError("当前状态不支持暂停")
            run.pause_requested = True
            session.commit()
            session.expunge(run)
            return run

    def resume_run(self, run_id: str, *, decision: Any = None) -> WorkflowRun:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise NotFoundError(f"工作流运行不存在: {run_id}")
            article = session.get(Article, run.article_id)
            if run.status == RunStatus.PAUSED:
                resume_value: Any = {"type": "continue"}
            elif run.status == RunStatus.WAITING_REVIEW:
                payload = decision if isinstance(decision, dict) else {}
                action = payload.get("decision")
                feedback = str(payload.get("feedback") or "").strip()
                if action not in {"approve", "reject"}:
                    raise ValidationError("审稿决策需要 approve 或 reject")
                if action == "reject" and not feedback:
                    raise ValidationError("驳回需要填写意见")
                resume_value = {"decision": action, "feedback": feedback}
            elif run.status == RunStatus.WAITING_PUBLISH:
                if decision not in {"approve", "cancel"}:
                    raise ValidationError("发布确认需要 approve 或 cancel")
                resume_value = decision
            elif run.status == RunStatus.INTERRUPTED:
                resume_value = None
            else:
                raise ConflictError(
                    "当前状态不支持继续", details={"status": run.status}
                )
            run.status = RunStatus.RUNNING
            run.error = None
            if article is not None:
                article.status = ArticleStatus.RUNNING
                article.error = None
            session.commit()
            article_id = run.article_id
        self._emit("run.status", article_id, run_id, {"status": "running"})
        self._schedule(run_id, resume=resume_value)
        return self.get_run(run_id)

    def recover_orphans(self) -> list[str]:
        """Mark runs left ``running``/``pending`` by a previous process as interrupted."""
        recovered: list[str] = []
        with self.session_factory() as session:
            runs = list(
                session.scalars(
                    select(WorkflowRun).where(
                        WorkflowRun.status.in_({RunStatus.RUNNING, RunStatus.PENDING})
                    )
                )
            )
            for run in runs:
                run.status = RunStatus.INTERRUPTED
                run.pause_requested = False
                article = session.get(Article, run.article_id)
                if article is not None and article.status == ArticleStatus.RUNNING:
                    article.status = ArticleStatus.PAUSED
                recovered.append(run.id)
            session.commit()
        for run_id in recovered:
            self._emit("run.status", None, run_id, {"status": "interrupted"})
        return recovered

    def execute_sync(
        self, run_id: str, *, resume: Any = None, initial: bool = False
    ) -> dict:
        result = self._run_graph(run_id, resume=resume, initial=initial)
        self._finalize(run_id, result)
        return result

    # ---------- scheduling ----------

    def _schedule(
        self, run_id: str, *, resume: Any = None, initial: bool = False
    ) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("no running event loop; run %s not scheduled", run_id)
            return False
        task = loop.create_task(self._execute(run_id, resume=resume, initial=initial))
        with self._lock:
            self._tasks.add(task)
        task.add_done_callback(self._discard_task)
        return True

    def _discard_task(self, task: asyncio.Task) -> None:
        with self._lock:
            self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("workflow task failed: %s", error)

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_runs)
            self._semaphore_loop = loop
        return self._semaphore

    async def _execute(
        self, run_id: str, *, resume: Any = None, initial: bool = False
    ) -> None:
        async with self._get_semaphore():
            try:
                result = await asyncio.to_thread(
                    self._run_graph, run_id, resume=resume, initial=initial
                )
            except Exception as exc:  # noqa: BLE001 - never lose the run
                logger.exception("workflow execution failed for run %s", run_id)
                self._mark_failed(run_id, str(exc))
                return
        self._finalize(run_id, result)

    # ---------- graph execution ----------

    def _checkpoint_path(self) -> Path:
        url = self.settings.effective_checkpoint_url
        if url.startswith("sqlite:///"):
            return Path(url.removeprefix("sqlite:///"))
        if url.startswith("sqlite://"):
            return Path(url.removeprefix("sqlite://"))
        raise ValidationError(f"Unsupported checkpoint url: {url}")

    def _run_graph(
        self, run_id: str, *, resume: Any = None, initial: bool = False
    ) -> dict:
        path = self._checkpoint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            saver = SqliteSaver(conn)
            saver.setup()
            graph = build_graph(self.nodes, saver)
            config = {"configurable": {"thread_id": run_id}}
            if resume is not None:
                payload: Any = Command(resume=resume)
            elif initial:
                payload = self._initial_state(run_id)
            else:
                snapshot = graph.get_state(config)
                if not snapshot.values:
                    payload = self._initial_state(run_id)
                elif snapshot.next and "pause" in snapshot.next:
                    # A recovered run may have crashed while suspended in the
                    # pause node. Resume that interrupt so recovery continues
                    # on the next invocation instead of pausing again.
                    payload = Command(resume={"type": "continue"})
                else:
                    payload = None
            run = self.get_run(run_id)
            metadata = {"run_id": run_id, "article_id": run.article_id}
            with trace_attributes(
                session_id=run_id,
                trace_name="workflow.run",
                metadata=metadata,
                tags=["workflow"],
            ):
                with trace_span(
                    "workflow.run",
                    input={"run_id": run_id, "initial": initial},
                    metadata=metadata,
                ) as span:
                    try:
                        result = graph.invoke(payload, config)
                    except Exception as exc:
                        if span is not None:
                            span.update(
                                output={"error": str(exc)},
                                level="ERROR",
                                status_message=str(exc),
                            )
                        raise
                    if span is not None:
                        span.update(output={"status": "completed"})
                    return result
        finally:
            conn.close()

    def _initial_state(self, run_id: str) -> dict:
        run = self.get_run(run_id)
        return {
            "article_id": run.article_id,
            "run_id": run.id,
            "revision_count": run.revision_count,
            "max_revisions": run.max_revisions,
            "stage_error": None,
            "review_verdict": None,
            "rollback_target": None,
            "pause_requested": False,
        }

    # ---------- finalization ----------

    def _finalize(self, run_id: str, result: dict) -> None:
        interrupts = result.get("__interrupt__") or []
        if interrupts:
            value = getattr(interrupts[0], "value", None) or {}
            if isinstance(value, dict) and value.get("type") == "publish_confirmation":
                self._set_status(run_id, RunStatus.WAITING_PUBLISH, ArticleStatus.WAITING_PUBLISH)
                self._emit(
                    "run.status",
                    None,
                    run_id,
                    {"status": RunStatus.WAITING_PUBLISH, "summary": value.get("summary")},
                )
            elif isinstance(value, dict) and value.get("type") == "review_decision":
                self._set_status(run_id, RunStatus.WAITING_REVIEW, ArticleStatus.WAITING_REVIEW)
                self._emit(
                    "run.status",
                    None,
                    run_id,
                    {
                        "status": RunStatus.WAITING_REVIEW,
                        "verdict": value.get("verdict"),
                        "rollback_to": value.get("rollback_to"),
                    },
                )
            else:
                self._set_status(run_id, RunStatus.PAUSED, ArticleStatus.PAUSED)
                self._emit("run.status", None, run_id, {"status": RunStatus.PAUSED})
            return

        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                return
            article = session.get(Article, run.article_id)
            if result.get("stage_error"):
                run.status = RunStatus.FAILED
                if article is not None:
                    article.status = ArticleStatus.FAILED
                    article.error = result["stage_error"]
            elif (
                result.get("review_verdict") == "fail"
                and result.get("review_human_decision") != "approve"
                and int(result.get("revision_count", 0))
                >= int(result.get("max_revisions", self.settings.max_revisions))
            ):
                run.status = RunStatus.NEEDS_HUMAN
                if article is not None:
                    article.status = ArticleStatus.NEEDS_HUMAN
            else:
                run.status = RunStatus.COMPLETED
                if article is not None:
                    if result.get("publish_result") == "published":
                        article.status = ArticleStatus.PUBLISHED
                    elif result.get("publish_result") in {"partial", "cancelled"}:
                        article.status = ArticleStatus.WAITING_PUBLISH
                    elif article.status == ArticleStatus.RUNNING:
                        article.status = ArticleStatus.PUBLISHED
                    article.error = None
            session.commit()
            status = run.status
        self._emit("run.status", None, run_id, {"status": status, "finished": True})

    def _set_status(self, run_id: str, run_status: str, article_status: str) -> None:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                return
            run.status = run_status
            article = session.get(Article, run.article_id)
            if article is not None:
                article.status = article_status
            session.commit()

    def _mark_failed(self, run_id: str, message: str) -> None:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                return
            run.status = RunStatus.FAILED
            run.error = message
            article = session.get(Article, run.article_id)
            if article is not None:
                article.status = ArticleStatus.FAILED
                article.error = message
            session.commit()
        self._emit("run.status", None, run_id, {"status": RunStatus.FAILED, "error": message})

    def _emit(
        self, event_type: str, article_id: str | None, run_id: str | None, data: dict
    ) -> None:
        event_bus.publish(
            Event(type=event_type, article_id=article_id, run_id=run_id, data=data)
        )
