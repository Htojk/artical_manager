"""End-to-end API journeys: happy path, rollback, recovery and cost."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.constants import STAGE_ORDER, RunStatus, Stage
from app.core.events import event_bus
from app.models.article import (
    Article,
    DraftVersion,
    OutlineVersion,
    PublishRecord,
    StageRun,
    WorkflowRun,
)
from app.models.llm import LLMCall, ModelProfile


def _create_article(client, *, confirmation: bool = False) -> str:
    response = client.post(
        "/api/articles",
        json={
            "title": "",
            "topic_mode": "ai",
            "target_platforms": ["mock"],
            "publish_confirmation": confirmation,
        },
    )
    assert response.status_code == 201
    return response.json()["article"]["id"]


def _choose_topic(client, article_id: str) -> None:
    recommended = client.post(
        f"/api/articles/{article_id}/topics/recommend", json={}
    )
    assert recommended.status_code == 200
    topics = recommended.json()["items"]
    assert len(topics) == 5
    selected = client.post(f"/api/topics/{topics[0]['id']}/select")
    assert selected.status_code == 200


def test_api_happy_path_with_confirmation_and_events(client_env):
    client = client_env.client
    article_id = _create_article(client, confirmation=True)
    _choose_topic(client, article_id)

    queue = event_bus.subscribe()
    try:
        started = client.post(f"/api/articles/{article_id}/run")
        assert started.status_code == 202
        run = started.json()
        client_env.runner.execute_sync(run["id"], initial=True)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
    finally:
        event_bus.unsubscribe(queue)

    waiting = client.get(f"/api/runs/{run['id']}").json()
    assert waiting["status"] == RunStatus.WAITING_PUBLISH
    assert (
        client.get(f"/api/articles/{article_id}").json()["article"]["status"]
        == "waiting_publish"
    )

    for stage in STAGE_ORDER[:-1]:
        detail = client.get(f"/api/articles/{article_id}/stages/{stage}")
        assert detail.status_code == 200, stage
        assert detail.json()["stage_run"]["status"] == "completed"
    publishing = client.get(f"/api/articles/{article_id}/stages/publishing").json()
    assert publishing["stage_run"] is None
    timeline = client.get(f"/api/articles/{article_id}/stages").json()
    assert [item["stage"] for item in timeline["stages"]] == list(STAGE_ORDER)
    assert timeline["stages"][-1]["status"] == "pending"
    assert client.get(f"/api/articles/{article_id}/stages/writing").json()["content"]["latest"][
        "content_md"
    ]
    assert client.get(f"/api/articles/{article_id}/stages/research").json()["content"][
        "sources"
    ]

    summary = client.get(f"/api/articles/{article_id}/confirm-summary")
    assert summary.status_code == 200
    assert summary.json()["platforms"]

    queue = event_bus.subscribe()
    try:
        confirmed = client.post(
            f"/api/articles/{article_id}/confirm-publish", json={"decision": "approve"}
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == RunStatus.RUNNING
        client_env.runner.execute_sync(run["id"], resume="approve")
        publish_events = []
        while not queue.empty():
            publish_events.append(queue.get_nowait())
    finally:
        event_bus.unsubscribe(queue)

    assert [event.data["stage"] for event in publish_events if event.type == "stage.status"] == [
        Stage.PUBLISHING,
        Stage.PUBLISHING,
    ]
    assert any(event.type == "publish.updated" for event in publish_events)

    finished = client.get(f"/api/runs/{run['id']}").json()
    assert finished["status"] == RunStatus.COMPLETED
    article = client.get(f"/api/articles/{article_id}").json()["article"]
    assert article["status"] == "published"
    records = client.get(f"/api/articles/{article_id}/publish/records").json()["items"]
    assert [item["status"] for item in records] == ["published"]

    types = [event.type for event in events]
    assert types.count("stage.status") == (len(STAGE_ORDER) - 1) * 2
    assert "review.completed" in types


def _rollback_plan(dimension: str) -> list[dict]:
    fail = {
        "fact": 90,
        "structure": 90,
        "readability": 90,
        "compliance": 90,
        "originality": 90,
        "_critical": [dimension],
        "_locations": {dimension: "第二节 结论"},
    }
    fail[dimension] = 0
    passed = {
        "fact": 90,
        "structure": 90,
        "readability": 90,
        "compliance": 90,
        "originality": 90,
    }
    return [fail, passed]


def test_api_rollback_routes_by_issue_type_and_keeps_versions(
    client_env, article_factory
):
    client = client_env.client

    fact_article = article_factory(platforms=["mock"])
    client_env.controller.review_plan = _rollback_plan("fact")
    fact_run = client.post(f"/api/articles/{fact_article}/run").json()
    client_env.runner.execute_sync(fact_run["id"], initial=True)
    with client_env.session_factory() as session:
        fact_attempts = list(
            session.scalars(
                select(StageRun.attempt).where(
                    StageRun.run_id == fact_run["id"], StageRun.stage == Stage.RESEARCH
                )
            )
        )
        assert max(fact_attempts) == 2
        assert session.query(OutlineVersion).filter_by(article_id=fact_article).count() == 2
        assert session.query(DraftVersion).filter_by(article_id=fact_article).count() == 2
    assert client.get(f"/api/runs/{fact_run['id']}").json()["revision_count"] == 1

    structure_article = article_factory(platforms=["mock"])
    client_env.controller.review_calls = 0
    client_env.controller.review_plan = _rollback_plan("structure")
    structure_run = client.post(f"/api/articles/{structure_article}/run").json()
    client_env.runner.execute_sync(structure_run["id"], initial=True)
    with client_env.session_factory() as session:
        outlines = list(
            session.scalars(
                select(OutlineVersion)
                .where(OutlineVersion.article_id == structure_article)
                .order_by(OutlineVersion.version)
            )
        )
        assert [item.version for item in outlines] == [1, 2]
        assert outlines[1].created_by == "review_revision"
        assert session.query(DraftVersion).filter_by(article_id=structure_article).count() == 2
    assert client.get(f"/api/runs/{structure_run['id']}").json()["revision_count"] == 1


def test_api_pause_resume_recovery_does_not_repeat_finished_stages(
    client_env, article_factory
):
    client = client_env.client
    article_id = article_factory(platforms=["mock"])
    run = client.post(f"/api/articles/{article_id}/run").json()

    def pause_during_draft() -> None:
        with client_env.session_factory() as session:
            session.get(WorkflowRun, run["id"]).pause_requested = True
            session.commit()

    client_env.controller.on_draft = pause_during_draft
    client_env.runner.execute_sync(run["id"], initial=True)
    client_env.controller.on_draft = None

    paused = client.get(f"/api/runs/{run['id']}").json()
    assert paused["status"] == RunStatus.PAUSED
    timeline = client.get(f"/api/articles/{article_id}/stages").json()["stages"]
    assert [item["stage"] for item in timeline] == list(STAGE_ORDER)
    assert [item["status"] for item in timeline[:4]] == ["completed"] * 4
    assert timeline[4]["status"] == "pending"
    with client_env.session_factory() as session:
        paused_stages = list(
            session.scalars(select(StageRun).where(StageRun.run_id == run["id"]))
        )
    assert [item.stage for item in paused_stages] == list(STAGE_ORDER[:4])
    assert all(item.status == "completed" for item in paused_stages)

    resumed = client.post(f"/api/runs/{run['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == RunStatus.RUNNING
    client_env.runner.execute_sync(run["id"], resume={"type": "continue"})

    assert client.get(f"/api/runs/{run['id']}").json()["status"] == RunStatus.COMPLETED
    with client_env.session_factory() as session:
        stages = list(
            session.scalars(select(StageRun).where(StageRun.run_id == run["id"]))
        )
        assert {stage.stage for stage in stages} == set(STAGE_ORDER)
        assert {stage.attempt for stage in stages} == {1}
        assert session.query(DraftVersion).filter_by(article_id=article_id).count() == 1


def test_api_cost_report_matches_model_prices_and_marks_missing(
    client_env, article_factory
):
    from app.analytics.cost import compute_cost, record_llm_call

    client = client_env.client
    article_id = article_factory(platforms=["mock"])
    run = client.post(f"/api/articles/{article_id}/run").json()
    client_env.runner.execute_sync(run["id"], initial=True)

    with client_env.session_factory() as session:
        profile = session.scalar(select(ModelProfile).where(ModelProfile.enabled.is_(True)))
        assert profile.input_price_per_1k is not None
        assert profile.output_price_per_1k is not None
        priced = record_llm_call(
            session,
            model=profile.model,
            article_id=article_id,
            run_id=run["id"],
            stage=Stage.WRITING,
            prompt_tokens=1000,
            completion_tokens=500,
        )
        expected = compute_cost(
            1000,
            500,
            profile.input_price_per_1k,
            profile.output_price_per_1k,
        )
        assert priced.cost == expected
        record_llm_call(
            session,
            model="unpriced-model",
            article_id=article_id,
            run_id=run["id"],
            stage=Stage.RESEARCH,
            prompt_tokens=800,
            completion_tokens=200,
        )
        stored = session.scalar(
            select(func.sum(LLMCall.cost)).where(LLMCall.article_id == article_id)
        )

    report = client.get("/api/analytics/costs", params={"article_id": article_id})
    assert report.status_code == 200
    body = report.json()
    assert body["total_cost"] == round(float(stored), 6)
    by_stage = {item["stage"]: item for item in body["by_stage"]}
    assert by_stage[Stage.WRITING]["cost"] == expected
    assert by_stage[Stage.WRITING]["prompt_tokens"] == 1000
    assert by_stage[Stage.WRITING]["completion_tokens"] == 500
    assert by_stage[Stage.RESEARCH]["price_missing_calls"] == 1
    assert by_stage[Stage.RESEARCH]["cost"] == 0
    assert body["article_id"] == article_id
