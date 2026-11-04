"""LangGraph workflow: order, review rollback, confirmation, pause, recovery."""

from __future__ import annotations

from sqlalchemy import select

from app.article_generation.workflow.graph import build_graph
from app.core.constants import (
    STAGE_ORDER,
    ArticleStatus,
    RunStatus,
    Stage,
    StageStatus,
)
from app.models.article import (
    Article,
    DraftVersion,
    FormattedOutput,
    OutlineVersion,
    PublishRecord,
    ReviewDecision,
    StageRun,
    WorkflowRun,
)


def _run(client_env, article_id):
    run = client_env.runner.start_run(article_id)
    client_env.runner.execute_sync(run.id, initial=True)
    return client_env.runner.get_run(run.id)


def _drain_events(client_env, queue):
    """Let the app loop deliver events scheduled with ``call_soon_threadsafe``.

    ``execute_sync`` publishes from the test thread while the TestClient loop
    runs in its portal thread, so draining the queue immediately can observe
    events out of order. Yielding one loop iteration flushes pending callbacks.
    """
    import asyncio

    client_env.client.portal.call(asyncio.sleep, 0)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def _stages(client_env, run_id):
    with client_env.session_factory() as session:
        rows = list(
            session.scalars(select(StageRun).where(StageRun.run_id == run_id))
        )
        return sorted(
            rows,
            key=lambda item: (STAGE_ORDER.index(item.stage), item.attempt),
        )


def _article(client_env, article_id):
    with client_env.session_factory() as session:
        return session.get(Article, article_id)


def test_graph_compiles_with_all_nodes():
    from app.article_generation.workflow.nodes import WorkflowNodes

    graph = build_graph(WorkflowNodes.__new__(WorkflowNodes), checkpointer=None)
    assert set(graph.get_graph().nodes) >= {
        "topic",
        "research",
        "outline",
        "write",
        "review",
        "format",
        "publish",
        "pause",
        "halt",
    }


def test_happy_path_runs_seven_stages(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    assert run.status == RunStatus.COMPLETED
    assert _article(client_env, article_id).status == ArticleStatus.PUBLISHED

    stages = _stages(client_env, run.id)
    assert [stage.stage for stage in stages] == list(STAGE_ORDER)
    assert all(stage.status == StageStatus.COMPLETED for stage in stages)
    assert all(stage.started_at and stage.finished_at for stage in stages)

    with client_env.session_factory() as session:
        assert session.query(OutlineVersion).filter_by(article_id=article_id).count() == 1
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 1
        output = session.query(FormattedOutput).filter_by(article_id=article_id, platform="mock").one()
        assert output.status == "ready"
        record = session.query(PublishRecord).filter_by(article_id=article_id, platform="mock").one()
        assert record.status == "published"
        assert record.remote_id


def test_review_pass_waits_for_human_approval_when_auto_advance_is_off(
    client_env, article_factory
):
    changed = client_env.client.put(
        "/api/settings/auto_review_advance", json={"value": False}
    )
    assert changed.status_code == 200

    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    assert run.status == RunStatus.WAITING_REVIEW
    assert _article(client_env, article_id).status == ArticleStatus.WAITING_REVIEW
    stages = _stages(client_env, run.id)
    assert [stage.stage for stage in stages] == list(STAGE_ORDER[:6])
    assert all(stage.status == StageStatus.COMPLETED for stage in stages)
    with client_env.session_factory() as session:
        assert session.query(FormattedOutput).filter_by(article_id=article_id).count() == 0

    client_env.runner.execute_sync(run.id, resume={"decision": "approve"})
    finished = client_env.runner.get_run(run.id)
    assert finished.status == RunStatus.COMPLETED
    assert [stage.stage for stage in _stages(client_env, run.id)] == list(STAGE_ORDER)


def test_human_approval_advances_failed_review_to_formatting(
    client_env, article_factory
):
    client_env.client.put("/api/settings/auto_review_advance", json={"value": False})
    client_env.controller.review_plan = [
        {
            "fact": 20,
            "structure": 80,
            "readability": 80,
            "compliance": 80,
            "originality": 80,
            "_critical": ["fact"],
        }
    ]
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    assert run.status == RunStatus.WAITING_REVIEW
    assert run.revision_count == 1
    assert not any(
        stage.stage == Stage.FORMATTING and stage.status == StageStatus.COMPLETED
        for stage in _stages(client_env, run.id)
    )

    client_env.runner.execute_sync(run.id, resume={"decision": "approve"})
    finished = client_env.runner.get_run(run.id)
    assert finished.status == RunStatus.COMPLETED
    assert _article(client_env, article_id).status == ArticleStatus.PUBLISHED
    with client_env.session_factory() as session:
        assert session.query(FormattedOutput).filter_by(article_id=article_id).count() == 1


def test_human_rejection_routes_to_outline_and_regenerates(
    client_env, article_factory
):
    client_env.client.put("/api/settings/auto_review_advance", json={"value": False})
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)
    assert run.status == RunStatus.WAITING_REVIEW
    assert run.revision_count == 0

    client_env.runner.execute_sync(
        run.id, resume={"decision": "reject", "feedback": "章节结构需要调整"}
    )
    waiting = client_env.runner.get_run(run.id)

    assert waiting.status == RunStatus.WAITING_REVIEW
    assert waiting.revision_count == 0
    with client_env.session_factory() as session:
        decision = session.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.run_id == run.id)
            .order_by(ReviewDecision.created_at.desc())
        )
        assert decision.decision == "rejected"
        assert decision.feedback == "章节结构需要调整"
        assert decision.rollback_to == Stage.OUTLINE
        assert session.query(OutlineVersion).filter_by(article_id=article_id).count() == 2
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 2
        latest_outline = session.scalars(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        ).first()
        assert "人工驳回意见" in latest_outline.note
        assert "章节结构需要调整" in latest_outline.note

    client_env.runner.execute_sync(run.id, resume={"decision": "approve"})
    finished = client_env.runner.get_run(run.id)
    assert finished.status == RunStatus.COMPLETED
    assert _article(client_env, article_id).status == ArticleStatus.PUBLISHED


def test_human_rejection_to_writing_revises_full_draft(
    client_env, article_factory
):
    client_env.client.put("/api/settings/auto_review_advance", json={"value": False})
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    client_env.runner.execute_sync(
        run.id, resume={"decision": "reject", "feedback": "整体表达太啰嗦"}
    )
    waiting = client_env.runner.get_run(run.id)
    assert waiting.status == RunStatus.WAITING_REVIEW

    with client_env.session_factory() as session:
        decision = session.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.run_id == run.id)
            .order_by(ReviewDecision.created_at.desc())
        )
        assert decision.rollback_to == Stage.WRITING
        latest_draft = session.scalars(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        ).first()
        assert "人工驳回意见" in latest_draft.note
        assert "整体表达太啰嗦" in latest_draft.note
        assert session.query(OutlineVersion).filter_by(article_id=article_id).count() == 1


def test_human_rejection_to_research_regenerates_full_chain(
    client_env, article_factory
):
    client_env.client.put("/api/settings/auto_review_advance", json={"value": False})
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    client_env.runner.execute_sync(
        run.id, resume={"decision": "reject", "feedback": "数据来源不可靠，需要补充权威资料"}
    )
    waiting = client_env.runner.get_run(run.id)
    assert waiting.status == RunStatus.WAITING_REVIEW
    assert waiting.revision_count == 0

    with client_env.session_factory() as session:
        decision = session.scalar(
            select(ReviewDecision)
            .where(ReviewDecision.run_id == run.id)
            .order_by(ReviewDecision.created_at.desc())
        )
        assert decision.rollback_to == Stage.RESEARCH
        assert session.query(OutlineVersion).filter_by(article_id=article_id).count() == 2
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 2

    attempts: dict[str, int] = {}
    for stage in _stages(client_env, run.id):
        attempts[stage.stage] = max(attempts.get(stage.stage, 0), stage.attempt)
    for stage in (Stage.RESEARCH, Stage.OUTLINE, Stage.WRITING):
        assert attempts[stage] == 2


def test_review_decision_routing_by_verdict_and_target():
    from app.article_generation.workflow.routing import (
        route_after_review,
        route_after_review_decision,
    )

    assert (
        route_after_review({"review_verdict": "pass", "review_human_required": True})
        == "review_decision"
    )
    assert route_after_review({"review_verdict": "pass"}) == "format"
    assert route_after_review({"review_verdict": "fail", "rollback_target": Stage.OUTLINE}) == "outline"
    assert route_after_review_decision({"review_human_decision": "approve"}) == "format"
    assert (
        route_after_review_decision(
            {"review_human_decision": "reject", "review_rejection_target": Stage.RESEARCH}
        )
        == "research"
    )
    assert (
        route_after_review_decision(
            {"review_human_decision": "reject", "review_rejection_target": Stage.OUTLINE}
        )
        == "outline"
    )
    assert route_after_review_decision({"review_human_decision": "reject"}) == "write"


def test_duplicate_active_run_rejected(client_env, article_factory):
    import pytest

    from app.core.errors import ConflictError

    article_id = article_factory()
    client_env.runner.start_run(article_id)
    with pytest.raises(ConflictError):
        client_env.runner.start_run(article_id)


def test_requires_topic(client_env):
    import pytest

    from app.core.errors import ValidationError
    from app.models.article import Article

    with client_env.session_factory() as session:
        article = Article(target_platforms=["mock"])
        session.add(article)
        session.commit()
        article_id = article.id
    with pytest.raises(ValidationError):
        client_env.runner.start_run(article_id)


def test_review_rollback_to_research_then_pass(client_env, article_factory):
    client_env.controller.review_plan = [
        {
            "fact": 30,
            "structure": 80,
            "readability": 80,
            "compliance": 80,
            "originality": 80,
            "_critical": ["fact"],
        },
        {
            "fact": 90,
            "structure": 90,
            "readability": 90,
            "compliance": 90,
            "originality": 90,
        },
    ]
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)

    assert run.status == RunStatus.COMPLETED
    assert run.revision_count == 1
    with client_env.session_factory() as session:
        research_attempts = list(
            session.scalars(
                select(StageRun.attempt).where(
                    StageRun.run_id == run.id, StageRun.stage == Stage.RESEARCH
                )
            )
        )
        assert max(research_attempts) == 2
        assert session.query(OutlineVersion).filter_by(article_id=article_id).count() == 2
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 2
        assert session.query(PublishRecord).filter_by(article_id=article_id).count() == 1


def test_review_rollback_to_outline_revises_and_keeps_old_version(
    client_env, article_factory
):
    client_env.controller.review_plan = [
        {
            "fact": 90,
            "structure": 0,
            "readability": 90,
            "compliance": 90,
            "originality": 90,
            "_critical": ["structure"],
            "_locations": {"structure": "第二节 结论"},
        },
        {
            "fact": 90,
            "structure": 90,
            "readability": 90,
            "compliance": 90,
            "originality": 90,
        },
    ]
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)
    assert run.status == RunStatus.COMPLETED
    with client_env.session_factory() as session:
        outlines = list(
            session.scalars(
                select(OutlineVersion)
                .where(OutlineVersion.article_id == article_id)
                .order_by(OutlineVersion.version)
            )
        )
        assert [item.version for item in outlines] == [1, 2]
        assert outlines[0].created_by == "model"
        assert outlines[1].created_by == "review_revision"
        assert "审核修订" in outlines[1].note
        assert outlines[1].content["sections"]
        drafts = list(
            session.scalars(
                select(DraftVersion)
                .where(DraftVersion.article_id == article_id)
                .order_by(DraftVersion.version)
            )
        )
        assert [item.version for item in drafts] == [1, 2]
        assert drafts[1].created_by == "model"


def test_review_rollback_to_writing_does_targeted_revision(client_env, article_factory):
    client_env.controller.review_plan = [
        {
            "fact": 90,
            "structure": 90,
            "readability": 0,
            "compliance": 90,
            "originality": 90,
            "_critical": ["readability"],
            "_locations": {"readability": "## 第二节 结论"},
        },
        {
            "fact": 90,
            "structure": 90,
            "readability": 90,
            "compliance": 90,
            "originality": 90,
        },
    ]
    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)
    assert run.status == RunStatus.COMPLETED
    with client_env.session_factory() as session:
        drafts = list(
            session.scalars(
                select(DraftVersion)
                .where(DraftVersion.article_id == article_id)
                .order_by(DraftVersion.version)
            )
        )
        assert [draft.version for draft in drafts] == [1, 2]
        assert drafts[1].created_by == "review_revision"
        assert "定向修订" in drafts[1].note
        assert "## 第一节 背景\n\n这是第一段正文，引用来源 [1]。\n\n" in drafts[1].content_md
        assert "定向修订后的结论段落。" in drafts[1].content_md
        assert "这是第二段正文，给出可执行建议。" not in drafts[1].content_md


def test_revision_limit_needs_human(client_env, article_factory):
    fail = {
        "fact": 90,
        "structure": 60,
        "readability": 60,
        "compliance": 90,
        "originality": 60,
        "_critical": ["structure"],
    }
    client_env.controller.review_plan = [fail]
    article_id = article_factory()
    run = _run(client_env, article_id)
    assert run.status == RunStatus.NEEDS_HUMAN
    assert run.revision_count == run.max_revisions
    assert _article(client_env, article_id).status == ArticleStatus.NEEDS_HUMAN
    assert "上限" in (_article(client_env, article_id).error or "")


def test_publish_confirmation_and_approve(client_env, article_factory):
    article_id = article_factory(platforms=["mock"], confirmation=True)
    run = _run(client_env, article_id)
    assert run.status == RunStatus.WAITING_PUBLISH
    assert _article(client_env, article_id).status == ArticleStatus.WAITING_PUBLISH
    with client_env.session_factory() as session:
        assert session.query(PublishRecord).filter_by(article_id=article_id).count() == 0
        assert session.query(FormattedOutput).filter_by(article_id=article_id).count() == 1

    client_env.runner.execute_sync(run.id, resume="approve")
    run = client_env.runner.get_run(run.id)
    assert run.status == RunStatus.COMPLETED
    assert _article(client_env, article_id).status == ArticleStatus.PUBLISHED


def test_publish_confirmation_cancel(client_env, article_factory):
    article_id = article_factory(platforms=["mock"], confirmation=True)
    run = _run(client_env, article_id)
    assert run.status == RunStatus.WAITING_PUBLISH

    client_env.runner.execute_sync(run.id, resume="cancel")
    run = client_env.runner.get_run(run.id)
    assert run.status == RunStatus.COMPLETED
    article = _article(client_env, article_id)
    assert article.status == ArticleStatus.WAITING_PUBLISH
    with client_env.session_factory() as session:
        assert session.query(PublishRecord).filter_by(article_id=article_id).count() == 0


def test_pause_and_resume_between_stages(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    run = client_env.runner.start_run(article_id)
    client_env.runner.request_pause(run.id)
    client_env.runner.execute_sync(run.id, initial=True)

    run = client_env.runner.get_run(run.id)
    assert run.status == RunStatus.PAUSED
    assert _article(client_env, article_id).status == ArticleStatus.PAUSED
    stages = _stages(client_env, run.id)
    assert [stage.stage for stage in stages] == [Stage.TOPIC]
    assert stages[0].status == StageStatus.COMPLETED

    client_env.runner.execute_sync(run.id, resume={"type": "continue"})
    run = client_env.runner.get_run(run.id)
    assert run.status == RunStatus.COMPLETED
    assert [stage.stage for stage in _stages(client_env, run.id)] == list(STAGE_ORDER)


def test_checkpoint_resume_from_writing_without_rerunning_finished_stages(
    client_env, article_factory
):
    article_id = article_factory(platforms=["mock"])
    run = client_env.runner.start_run(article_id)

    def pause_during_draft() -> None:
        with client_env.session_factory() as session:
            session.get(WorkflowRun, run.id).pause_requested = True
            session.commit()

    client_env.controller.on_draft = pause_during_draft
    client_env.runner.execute_sync(run.id, initial=True)
    assert client_env.runner.get_run(run.id).status == RunStatus.PAUSED
    stages = _stages(client_env, run.id)
    assert [stage.stage for stage in stages] == [
        Stage.TOPIC,
        Stage.RESEARCH,
        Stage.OUTLINE,
        Stage.WRITING,
    ]
    assert all(stage.status == StageStatus.COMPLETED for stage in stages)
    with client_env.session_factory() as session:
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 1

    client_env.controller.on_draft = None
    client_env.runner.execute_sync(run.id, resume={"type": "continue"})
    finished = client_env.runner.get_run(run.id)
    assert finished.status == RunStatus.COMPLETED

    stages = _stages(client_env, run.id)
    assert [stage.stage for stage in stages] == list(STAGE_ORDER)
    assert all(stage.status == StageStatus.COMPLETED for stage in stages)
    attempts = {stage.stage: stage.attempt for stage in stages}
    assert attempts[Stage.WRITING] == 1
    assert attempts[Stage.TOPIC] == 1
    assert attempts[Stage.RESEARCH] == 1
    assert attempts[Stage.OUTLINE] == 1
    with client_env.session_factory() as session:
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 1


def test_pause_rejected_in_terminal_state(client_env, article_factory):
    import pytest

    from app.core.errors import ConflictError

    article_id = article_factory(platforms=["mock"])
    run = _run(client_env, article_id)
    with pytest.raises(ConflictError):
        client_env.runner.request_pause(run.id)


def test_recover_orphans(client_env, article_factory):
    article_id = article_factory()
    run = client_env.runner.start_run(article_id)
    with client_env.session_factory() as session:
        db_run = session.get(WorkflowRun, run.id)
        db_run.status = RunStatus.RUNNING
        article = session.get(Article, article_id)
        article.status = ArticleStatus.RUNNING
        session.commit()

    recovered = client_env.runner.recover_orphans()
    assert run.id in recovered
    assert client_env.runner.get_run(run.id).status == RunStatus.INTERRUPTED
    assert _article(client_env, article_id).status == ArticleStatus.PAUSED


def test_restart_marks_orphan_and_resumes_without_repeating_finished_stages(
    client_env, article_factory
):
    from app.article_generation.workflow.runner import WorkflowRunner

    article_id = article_factory(platforms=["mock"])
    run = client_env.runner.start_run(article_id)

    def pause_during_draft() -> None:
        with client_env.session_factory() as session:
            session.get(WorkflowRun, run.id).pause_requested = True
            session.commit()

    client_env.controller.on_draft = pause_during_draft
    client_env.runner.execute_sync(run.id, initial=True)
    assert client_env.runner.get_run(run.id).status == RunStatus.PAUSED
    before = _stages(client_env, run.id)
    assert [stage.stage for stage in before] == [
        Stage.TOPIC,
        Stage.RESEARCH,
        Stage.OUTLINE,
        Stage.WRITING,
    ]
    assert all(stage.status == StageStatus.COMPLETED for stage in before)
    stage_ids = {stage.stage: stage.id for stage in before}

    # Simulate the process dying while the run was still marked active.
    with client_env.session_factory() as session:
        db_run = session.get(WorkflowRun, run.id)
        db_run.status = RunStatus.RUNNING
        db_run.pause_requested = False
        session.get(Article, article_id).status = ArticleStatus.RUNNING
        session.commit()

    client_env.controller.on_draft = None
    restarted = WorkflowRunner(
        client_env.session_factory,
        client_env.llm,
        client_env.registry,
        client_env.skill_registry,
        settings=client_env.settings,
        search_tool=client_env.search_tool,
    )
    assert run.id in restarted.recover_orphans()
    assert restarted.get_run(run.id).status == RunStatus.INTERRUPTED
    assert _article(client_env, article_id).status == ArticleStatus.PAUSED

    restarted.execute_sync(run.id)

    finished = restarted.get_run(run.id)
    assert finished.status == RunStatus.COMPLETED
    after = _stages(client_env, run.id)
    assert [stage.stage for stage in after] == list(STAGE_ORDER)
    assert all(stage.status == StageStatus.COMPLETED for stage in after)
    for stage in after:
        if stage.stage in stage_ids:
            assert stage.id == stage_ids[stage.stage]
            assert stage.attempt == 1
    with client_env.session_factory() as session:
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 1


def test_stage_failure_marks_run_failed(client_env, article_factory):
    article_id = article_factory()
    client_env.search_tool.error = RuntimeError("boom")
    # Search failure degrades, so force a hard failure in the outline stage instead.
    client_env.controller.outline_calls = 0

    class BrokenLLM:
        def structured(self, **kwargs):
            raise RuntimeError("model exploded")

        def get_binding(self, stage):
            raise RuntimeError("no binding")

    client_env.runner.context.llm = BrokenLLM()
    run = _run(client_env, article_id)
    assert run.status == RunStatus.FAILED
    article = _article(client_env, article_id)
    assert article.status == ArticleStatus.FAILED
    assert "model exploded" in (article.error or "")
    failed = [stage for stage in _stages(client_env, run.id) if stage.status == StageStatus.FAILED]
    assert failed and failed[0].stage == Stage.OUTLINE


def test_workflow_publishes_stage_event_sequence(client_env, article_factory):
    from app.core.events import event_bus

    queue = event_bus.subscribe()
    try:
        article_id = article_factory(platforms=["mock"])
        run = _run(client_env, article_id)
        events = _drain_events(client_env, queue)
    finally:
        event_bus.unsubscribe(queue)

    assert run.status == RunStatus.COMPLETED
    types = [event.type for event in events]
    assert types.count("stage.status") == len(STAGE_ORDER) * 2
    stage_events = [event for event in events if event.type == "stage.status"]
    assert [event.data["status"] for event in stage_events[::2]] == ["running"] * len(STAGE_ORDER)
    assert [event.data["status"] for event in stage_events[1::2]] == ["completed"] * len(STAGE_ORDER)
    assert [event.data["stage"] for event in stage_events[::2]] == list(STAGE_ORDER)
    assert all(event.run_id == run.id for event in events)
    assert all(event.article_id in {article_id, None} for event in events)
    assert all(event.article_id == article_id for event in stage_events)
    assert "review.completed" in types
    assert types[-1] in {"run.status", "publish.updated"}
