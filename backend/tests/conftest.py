"""Shared pytest fixtures: temp SQLite, fake LLM, app client."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings, reset_settings_cache  # noqa: E402
from app.core.db import reset_engine  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_search_guard_between_tests():
    """Keep process-wide throttle/cache state from leaking across tests."""
    from app.article_generation.research.search_guard import reset_search_guard

    reset_search_guard()
    yield
    reset_search_guard()


@pytest.fixture
def test_settings(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("APP_DATA_DIR", str(data_dir))
    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("APP_DATABASE_URL", f"sqlite:///{(data_dir / 'app.sqlite').as_posix()}")
    monkeypatch.setenv(
        "APP_CHECKPOINT_URL", f"sqlite:///{(data_dir / 'checkpoints.sqlite').as_posix()}"
    )
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("APP_SKILLS_DIR", str(BACKEND_ROOT.parent / "skills"))
    monkeypatch.setenv("APP_PROMPTS_DIR", str(BACKEND_ROOT / "app" / "prompts"))
    monkeypatch.setenv("APP_MAX_CONCURRENT_RUNS", "2")
    monkeypatch.setenv("APP_PUBLISH_CONFIRMATION", "true")
    monkeypatch.setenv("APP_MAX_REVISIONS", "3")
    monkeypatch.setenv("APP_DEEP_RESEARCH_ENABLED", "false")
    monkeypatch.setenv("APP_DEEP_REVISION_ENABLED", "false")
    monkeypatch.setenv("APP_MEMECUB_ENABLED", "false")
    monkeypatch.setenv("APP_MEMECUB_API_KEY", "")
    # Tracing must never reach a real Langfuse instance during tests.
    monkeypatch.setenv("APP_LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("APP_LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("APP_LANGFUSE_SECRET_KEY", "")
    # Keep tests independent of a developer's local .env model configuration.
    monkeypatch.setenv("APP_LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("APP_LLM_API_KEY", "test-api-key")
    monkeypatch.setenv("APP_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("APP_LLM_INPUT_PRICE_PER_1K", "0.0011")
    monkeypatch.setenv("APP_LLM_OUTPUT_PRICE_PER_1K", "0.0043")
    reset_settings_cache()
    reset_engine()
    settings = get_settings()
    settings.ensure_directories()
    yield settings
    reset_engine()
    reset_settings_cache()


@pytest.fixture
def db_session(test_settings):
    from app.core.db import configure_engine, get_session_factory, init_db

    configure_engine(settings=test_settings)
    init_db()
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@dataclass
class ClientBundle:
    client: object
    app: object
    settings: object
    session_factory: object
    controller: object
    llm: object
    runner: object
    registry: object
    skill_registry: object
    search_tool: object


@pytest.fixture
def client_env(test_settings):
    from fastapi.testclient import TestClient

    from app.article_generation.workflow.runner import WorkflowRunner
    from app.core.db import get_session_factory
    from app.core.llm import LLMService
    from app.main import create_app
    from app.platforms.registry import PlatformRegistry
    from app.skills.registry import SkillRegistry
    from tests.fakes import FakeController, FakeSearchTool, fake_model_factory, sample_results

    class NoScheduleRunner(WorkflowRunner):
        """Runner whose background scheduling is disabled so tests advance manually."""

        def _schedule(self, run_id, *, resume=None, initial=False):
            return False

    platform_registry = PlatformRegistry()
    platform_registry.discover()
    skill_registry = SkillRegistry(test_settings.skills_dir)
    app = create_app(
        test_settings,
        platform_registry=platform_registry,
        skill_registry=skill_registry,
        start_scheduler=False,
    )
    controller = FakeController()
    with TestClient(app) as client:
        session_factory = get_session_factory()
        llm = LLMService(
            session_factory,
            settings=test_settings,
            model_factory=fake_model_factory(controller),
        )
        search_tool = FakeSearchTool(results=sample_results())
        # Existing journeys assume a passing review advances automatically.
        # The production default is off; the gated path is covered in test_workflow.
        from app.models.system import Setting

        with session_factory() as session:
            setting = session.get(Setting, "auto_review_advance")
            if setting is None:
                session.add(Setting(key="auto_review_advance", value=True))
            else:
                setting.value = True
            session.commit()
        runner = NoScheduleRunner(
            session_factory,
            llm,
            platform_registry,
            skill_registry,
            settings=test_settings,
            search_tool=search_tool,
        )
        app.state.llm = llm
        app.state.runner = runner
        yield ClientBundle(
            client=client,
            app=app,
            settings=test_settings,
            session_factory=session_factory,
            controller=controller,
            llm=llm,
            runner=runner,
            registry=platform_registry,
            skill_registry=skill_registry,
            search_tool=search_tool,
        )
    reset_engine()


@pytest.fixture
def article_factory(client_env):
    from app.models.article import Article

    def create(*, title="", platforms=None, confirmation=False, topic_title="测试选题：AI 工程实践"):
        session = client_env.session_factory()
        try:
            article = Article(
                title=title,
                target_platforms=platforms or ["mock"],
                publish_confirmation=confirmation,
                topic_mode="manual",
            )
            session.add(article)
            session.commit()
            article_id = article.id
            from app.article_generation.topic_selection.service import TopicService

            service = TopicService(session, client_env.llm)
            topic = service.create_manual(article_id, title=topic_title, angle="工程实践")
            service.select(article_id, topic.id)
            return article_id
        finally:
            session.close()

    return create
