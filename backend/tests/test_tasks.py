"""Scheduled jobs: metric collection and evolution analysis."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.analytics.collector import CollectResult
from app.models.llm import StageModelBinding
from app.self_evolution.scheduler import run_analysis_once
from app.tasks import collect_metrics_job, evolution_analysis_job


def test_collect_metrics_job_returns_snapshot_count(client_env, monkeypatch):
    from app import tasks as tasks_module

    class FakeCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def collect(self):
            return CollectResult(snapshots=[object(), object()])

    monkeypatch.setattr(tasks_module, "MetricsCollector", FakeCollector)
    assert collect_metrics_job(client_env.session_factory, client_env.registry) == 2


def test_collect_metrics_job_swallows_failures(client_env, monkeypatch):
    from app import tasks as tasks_module

    class BrokenCollector:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def collect(self):
            raise RuntimeError("metrics down")

    monkeypatch.setattr(tasks_module, "MetricsCollector", BrokenCollector)
    assert collect_metrics_job(client_env.session_factory, client_env.registry) == 0


def test_evolution_job_respects_disabled_setting(client_env, monkeypatch):
    from app.self_evolution import scheduler as scheduler_module

    monkeypatch.setattr(
        scheduler_module, "get_settings", lambda: SimpleNamespace(evolution_enabled=False)
    )
    assert evolution_analysis_job(client_env.session_factory, client_env.llm) == 0


def test_evolution_job_only_creates_pending_suggestions(client_env, article_factory):
    from app.models.article import Article
    from app.schemas.artifacts import EvolvingSuggestion as Suggestion
    from app.core.constants import SuggestionStatus

    article_id = article_factory(platforms=["mock"])
    client_env.runner.execute_sync(
        client_env.runner.start_run(article_id).id, initial=True
    )
    client_env.controller.suggestions = [
        Suggestion(
            type="writing_rule",
            target_stage="writing",
            title="减少形容词",
            rationale="用户经常删除",
            evidence=["edit diff"],
            patch={"rule": "少用形容词"},
        )
    ]
    with client_env.session_factory() as session:
        before = {
            binding.stage: binding.model_profile_id
            for binding in session.scalars(select(StageModelBinding))
        }
        article_status = session.get(Article, article_id).status

    created = evolution_analysis_job(client_env.session_factory, client_env.llm)
    assert created == 1
    with client_env.session_factory() as session:
        from app.models.evolution import EvolutionSuggestion

        suggestions = list(session.scalars(select(EvolutionSuggestion)))
        assert [item.status for item in suggestions] == [SuggestionStatus.PENDING]
        after = {
            binding.stage: binding.model_profile_id
            for binding in session.scalars(select(StageModelBinding))
        }
        assert after == before
        assert session.get(Article, article_id).status == article_status
