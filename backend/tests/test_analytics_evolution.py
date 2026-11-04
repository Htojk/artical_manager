"""Cost accounting, metric collection, analytics and self-evolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.analytics.collector import MetricsCollector
from app.analytics.cost import (
    CostTracker,
    compute_cost,
    estimate_tokens,
    extract_usage,
    record_llm_call,
)
from app.analytics.service import AnalyticsService
from app.core.constants import SuggestionStatus
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.llm_context import llm_context
from app.core.security import CredentialCipher, CredentialService
from app.models.article import PublishRecord
from app.models.evolution import EvolutionSuggestion
from app.models.llm import LLMCall, ModelProfile
from app.schemas.artifacts import EvolvingSuggestion
from app.self_evolution.analyzer import EvolutionAnalyzer
from app.self_evolution.applier import EvolutionApplier


def test_compute_cost_and_lookup(client_env, db_session):
    assert compute_cost(1000, 2000, 0.0011, 0.0043) == pytest.approx(0.0097)
    assert compute_cost(1000, 2000, None, 0.0043) is None
    call = record_llm_call(
        db_session, model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=1000
    )
    assert call.cost == pytest.approx(0.0054)
    assert call.currency == "CNY"
    missing = record_llm_call(db_session, model="unknown-model", prompt_tokens=10)
    assert missing.price_missing
    assert missing.cost is None


def test_cost_tracker_records_usage(client_env):
    session_factory = client_env.session_factory
    with session_factory() as session:
        profile = session.scalar(select(ModelProfile))
        model_name = profile.model
    tracker = CostTracker(session_factory, model_name)
    tracker.on_llm_start({}, ["prompt"], run_id="r1")
    response = SimpleNamespace(
        llm_output={
            "token_usage": {"prompt_tokens": 1000, "completion_tokens": 500}
        },
        generations=[],
    )
    with llm_context(article_id=None, run_id="run-x", stage="writing"):
        tracker.on_llm_end(response, run_id="r1")
    with session_factory() as session:
        call = session.scalar(select(LLMCall).where(LLMCall.run_id == "run-x"))
        assert call.prompt_tokens == 1000
        assert call.completion_tokens == 500
        assert call.stage == "writing"
        assert not call.estimated
        assert call.cost == pytest.approx(0.00325)


def test_cost_tracker_estimates_when_usage_missing(client_env):
    session_factory = client_env.session_factory
    tracker = CostTracker(session_factory, "gpt-4o-mini")
    tracker.on_llm_start({}, ["hello world"], run_id="r2")
    message = SimpleNamespace(text="hello there")
    response = SimpleNamespace(
        llm_output={}, generations=[[SimpleNamespace(text="hello there", message=message)]]
    )
    tracker.on_llm_end(response, prompts=["hello world"], run_id="r2")
    with session_factory() as session:
        call = session.scalar(select(LLMCall).where(LLMCall.stage == "unknown"))
        assert call is not None
        assert call.estimated
        assert call.prompt_tokens > 0


def test_extract_usage_variants():
    assert extract_usage(SimpleNamespace(llm_output={}, generations=[])) is None
    response = SimpleNamespace(
        llm_output={"token_usage": {"input_tokens": 3, "output_tokens": 4}},
        generations=[],
    )
    assert extract_usage(response) == (3, 4)
    message = SimpleNamespace(usage_metadata={"input_tokens": 5, "output_tokens": 6})
    response = SimpleNamespace(
        llm_output={}, generations=[[SimpleNamespace(message=message)]]
    )
    assert extract_usage(response) == (5, 6)
    prompt, completion = estimate_tokens("hello world", "hello there")
    assert prompt > 0 and completion > 0


def test_collector_and_analytics(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client_env.runner.execute_sync(
        client_env.runner.start_run(article_id).id, initial=True
    )
    with client_env.session_factory() as session:
        credentials = CredentialService(session, CredentialCipher(client_env.settings))
        collector = MetricsCollector(session, client_env.registry, credentials)
        result = collector.collect(article_id)
        assert len(result.snapshots) == 1
        snapshot = result.snapshots[0]
        assert snapshot.source == "api"
        assert snapshot.views > 0

        manual = collector.add_manual(
            snapshot.publish_record_id,
            views=99,
            likes=1,
            comments=2,
            shares=3,
            revenue_cents=100,
        )
        assert manual.source == "manual"
        with pytest.raises(ValidationError):
            collector.add_manual(snapshot.publish_record_id, views=-1)
        with pytest.raises(NotFoundError):
            collector.add_manual("missing", views=1)

        latest = collector.latest_for_article(article_id)
        assert latest[0].views == 99

        analytics = AnalyticsService(session)
        summary = analytics.summary()
        assert summary["articles"] == 1
        assert summary["metrics"]["views"] == 99
        assert summary["metrics"]["revenue_yuan"] == 1.0
        performance = analytics.performance_rows()
        assert performance[0]["views"] == 99
        article_perf = analytics.article_performance(article_id)
        assert article_perf["latest_review"]["verdict"] == "pass"
        cost = analytics.article_cost(article_id)
        assert cost["title"]
        with pytest.raises(NotFoundError):
            analytics.article_cost("missing")


def test_evolution_analyze_approve_apply_rollback(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client_env.runner.execute_sync(
        client_env.runner.start_run(article_id).id, initial=True
    )
    with client_env.session_factory() as session:
        profile = session.scalar(select(ModelProfile))
        client_env.controller.suggestions = [
            EvolvingSuggestion(
                type="model_routing",
                target_stage="writing",
                title="写作阶段改用更便宜的模型",
                rationale="成本偏高且质量稳定",
                evidence=["average review 90"],
                patch={"stage": "writing", "model_profile_id": profile.id},
                expected_impact="成本下降 20%",
            )
        ]
        result = EvolutionAnalyzer(session, client_env.llm).analyze()
        assert len(result.suggestions) == 1
        suggestion = result.suggestions[0]
        assert suggestion.status == SuggestionStatus.PENDING
        suggestion_id = suggestion.id
        profile_id = profile.id

        applier = EvolutionApplier(session, client_env.settings)
        approved = applier.decide(suggestion_id, approve=True, note="ok")
        assert approved.status == SuggestionStatus.APPROVED
        with pytest.raises(ConflictError):
            applier.decide(suggestion_id, approve=True)

        applied = applier.apply(suggestion_id)
        assert applied.status == SuggestionStatus.APPLIED
        assert applied.before_snapshot["kind"] == "model"
        assert applied.baseline

        rolled_back = applier.rollback(suggestion_id)
        assert rolled_back.status == SuggestionStatus.ROLLED_BACK
        with pytest.raises(ConflictError):
            applier.apply(suggestion_id)

        another = EvolutionSuggestion(
            type="model_routing",
            target_stage="writing",
            title="x",
            rationale="y",
            patch={"stage": "writing", "model_profile_id": profile_id},
            status=SuggestionStatus.PENDING,
        )
        session.add(another)
        session.commit()
        rejected = applier.reject(another.id, note="no")
        assert rejected.status == SuggestionStatus.REJECTED
        with pytest.raises(ConflictError):
            applier.decide(another.id, approve=True)


def test_evolution_analyzer_without_articles(client_env):
    with client_env.session_factory() as session:
        result = EvolutionAnalyzer(session, client_env.llm).analyze()
        assert result.suggestions == []
        assert "model_profiles" in EvolutionAnalyzer(session, client_env.llm).current_config()


def test_manual_metric_record_not_found(client_env):
    with client_env.session_factory() as session:
        credentials = CredentialService(session, CredentialCipher(client_env.settings))
        collector = MetricsCollector(session, client_env.registry, credentials)
        with pytest.raises(NotFoundError):
            collector.add_manual("missing", views=1)


def test_evolution_guardrail_recommends_rollback_when_quality_drops(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client_env.runner.execute_sync(
        client_env.runner.start_run(article_id).id, initial=True
    )
    with client_env.session_factory() as session:
        suggestion = EvolutionSuggestion(
            type="model_routing",
            target_stage="writing",
            title="切换低成本模型",
            rationale="成本下降",
            status=SuggestionStatus.APPLIED,
            baseline={"average_review": 100.0, "rework_rate": 0.0},
            before_snapshot={"kind": "model"},
        )
        session.add(suggestion)
        session.commit()
        applier = EvolutionApplier(session, client_env.settings)
        evaluation = applier.refresh_effect(suggestion.id, window=10)
        assert evaluation["current"]["articles"] >= 1
        assert evaluation["current"]["average_review"] is not None
        assert evaluation["rollback_recommended"] is True
        assert suggestion.result == evaluation

        healthy = EvolutionSuggestion(
            type="writing_rule",
            target_stage="writing",
            title="调整写作规则",
            rationale="保持",
            status=SuggestionStatus.APPLIED,
            baseline={"average_review": 80.0},
            before_snapshot={"kind": "skill"},
        )
        session.add(healthy)
        session.commit()
        assert applier.refresh_effect(healthy.id)["rollback_recommended"] is False

        pending = EvolutionSuggestion(
            type="writing_rule",
            target_stage="writing",
            title="未应用",
            rationale="x",
            status=SuggestionStatus.PENDING,
        )
        session.add(pending)
        session.commit()
        with pytest.raises(ConflictError):
            applier.refresh_effect(pending.id)


def test_signal_collector_links_edit_review_metrics_and_cost(
    client_env, article_factory
):
    from app.analytics.cost import record_llm_call
    from app.article_generation.writing.service import WritingService
    from app.models.article import Article, DraftVersion, PublishRecord
    from app.self_evolution.signals import SignalCollector
    from app.skills.manager import SkillManager

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
    run = client_env.runner.start_run(article_id)
    client_env.runner.execute_sync(run.id, initial=True)

    with client_env.session_factory() as session:
        model_draft = session.scalar(
            select(DraftVersion)
            .where(
                DraftVersion.article_id == article_id,
                DraftVersion.created_by == "model",
            )
            .order_by(DraftVersion.version)
        )
        edited = model_draft.content_md.replace(
            "这是第一段正文，引用来源 [1]。",
            "用户改写后的第一段正文，补充了更多实操细节与背景说明。",
        )
        edited += "\n\n用户补充的结尾段落。"
        WritingService(
            session,
            client_env.llm,
            SkillManager(session, client_env.skill_registry),
        ).user_edit(article_id, content_md=edited, summary="用户定稿")
        record = session.scalar(
            select(PublishRecord).where(PublishRecord.article_id == article_id)
        )
        MetricsCollector(
            session,
            client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
        ).add_manual(record.id, views=1200, revenue_cents=350)
        record_llm_call(
            session,
            model="fake-model",
            prompt_tokens=1000,
            completion_tokens=200,
            article_id=article_id,
            run_id=run.id,
            stage="writing",
        )
        call = session.scalar(
            select(LLMCall).where(LLMCall.article_id == article_id)
        )
        call.cost = 0.42
        session.commit()

    with client_env.session_factory() as session:
        signal = SignalCollector(session).for_article(article_id)
        recent = SignalCollector(session).recent()
        article = session.get(Article, article_id)

    assert signal.article_id == article_id
    assert signal.title == article.title
    assert signal.rework_count == 1
    assert signal.review_average is not None and 0 < signal.review_average <= 100
    assert len(signal.review_issues) == 1
    assert signal.review_issues[0].startswith("fail/writing:")
    assert "-这是第一段正文" in signal.edit_diff
    assert "+用户改写后的第一段正文" in signal.edit_diff
    assert signal.user_edit_chars > 0
    assert signal.views == 1200
    assert signal.revenue_cents == 350
    assert signal.cost == pytest.approx(0.42)
    assert [item.article_id for item in recent] == [article_id]
