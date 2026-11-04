"""Tracing is optional, no-op by default and never breaks callers."""

from __future__ import annotations

from contextlib import contextmanager

import langfuse
import langfuse.langchain
import pytest

from app.core import tracing
from app.core.config import Settings


class FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class FakeObservation:
    def __init__(self, span: FakeSpan) -> None:
        self.span = span

    def __enter__(self) -> FakeSpan:
        return self.span

    def __exit__(self, *exc_info) -> bool:
        return False


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.spans: list[FakeSpan] = []
        self.closed = False

    def start_as_current_observation(self, **kwargs) -> FakeObservation:
        self.calls.append(kwargs)
        span = FakeSpan()
        self.spans.append(span)
        return FakeObservation(span)

    def shutdown(self) -> None:
        self.closed = True


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "langfuse_enabled": True,
        "langfuse_host": "http://langfuse.internal:3000",
        "langfuse_public_key": "pk-lf-test",
        "langfuse_secret_key": "sk-lf-test",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(autouse=True)
def _reset_tracing():
    tracing.shutdown_tracing(0.1)
    yield
    tracing.shutdown_tracing(0.1)


def test_disabled_without_explicit_enable():
    settings = _settings(langfuse_enabled=False)
    assert tracing.configure_tracing(settings) is False
    assert tracing.tracing_enabled() is False
    assert tracing.get_langfuse_handler() is None


def test_missing_credentials_keep_tracing_disabled(monkeypatch):
    # configure_logging() (run by app lifespan tests) replaces root handlers,
    # so capture the warning on the module logger instead of relying on caplog.
    messages: list[str] = []
    monkeypatch.setattr(
        tracing.logger,
        "warning",
        lambda message, *args: messages.append(message % args if args else message),
    )
    settings = _settings(langfuse_public_key="", langfuse_secret_key="")
    assert tracing.configure_tracing(settings) is False
    assert tracing.tracing_enabled() is False
    assert any("APP_LANGFUSE_PUBLIC_KEY" in message for message in messages)


def test_configure_initialises_client_and_handler(monkeypatch):
    captured: dict = {}

    class FakeLangfuse:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.closed = False

        def shutdown(self):
            self.closed = True

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", lambda: "handler")

    settings = _settings(env="staging", langfuse_sample_rate=0.25)
    assert tracing.configure_tracing(settings) is True
    assert tracing.tracing_enabled() is True
    assert tracing.get_langfuse_handler() == "handler"
    assert captured["host"] == "http://langfuse.internal:3000"
    assert captured["public_key"] == "pk-lf-test"
    assert captured["secret_key"] == "sk-lf-test"
    assert captured["sample_rate"] == 0.25
    assert captured["environment"] == "staging"

    tracing.shutdown_tracing(0.1)
    assert tracing.tracing_enabled() is False


def test_initialisation_failure_is_swallowed(monkeypatch):
    class BrokenLangfuse:
        def __init__(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(langfuse, "Langfuse", BrokenLangfuse)
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", lambda: "handler")

    assert tracing.configure_tracing(_settings()) is False
    assert tracing.tracing_enabled() is False


def test_trace_span_is_noop_when_disabled():
    with tracing.trace_span("stage.topic", metadata={"stage": "topic"}) as span:
        assert span is None


def test_trace_span_records_metadata_and_drops_none(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)

    with tracing.trace_span(
        "stage.topic",
        input={"article_id": "a1"},
        metadata={"stage": "topic", "attempt": None},
    ) as span:
        assert span is not None
        span.update(output="ok")

    assert client.calls[0]["name"] == "stage.topic"
    assert client.calls[0]["as_type"] == "span"
    assert client.calls[0]["input"] == {"article_id": "a1"}
    assert client.calls[0]["metadata"] == {"stage": "topic"}
    assert span.updates == [{"output": "ok"}]


def test_trace_attributes_noop_when_disabled():
    with tracing.trace_attributes(session_id="run-1", metadata={"a": 1}):
        pass


def test_trace_attributes_propagate(monkeypatch):
    calls: list[dict] = []

    @contextmanager
    def fake_propagate(**kwargs):
        calls.append(kwargs)
        yield

    monkeypatch.setattr(tracing, "_client", FakeClient())
    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)

    with tracing.trace_attributes(
        session_id="run-1",
        metadata={"article_id": "a1", "empty": None},
        tags=["topic"],
        trace_name="workflow.run",
    ):
        pass

    assert calls == [
        {
            "session_id": "run-1",
            "metadata": {"article_id": "a1"},
            "tags": ["topic"],
            "trace_name": "workflow.run",
        }
    ]


def test_trace_config_returns_none_when_disabled(monkeypatch):
    import app.core.llm as llm_module

    monkeypatch.setattr(llm_module, "get_langfuse_handler", lambda: None)
    assert llm_module.LLMService._trace_config("writing", "a1", "r1") is None


def test_trace_config_carries_stage_and_session(monkeypatch):
    import app.core.llm as llm_module

    monkeypatch.setattr(llm_module, "get_langfuse_handler", lambda: object())
    config = llm_module.LLMService._trace_config("writing", "a1", "r1")
    assert config == {
        "metadata": {
            "stage": "writing",
            "article_id": "a1",
            "run_id": "r1",
            "langfuse_session_id": "r1",
            "langfuse_tags": ["writing"],
        }
    }


def test_build_model_attaches_handler_only_when_enabled(test_settings, monkeypatch):
    import langchain_openai

    from app.core.db import configure_engine, get_session_factory, init_db
    from app.core.llm import LLMService
    from app.seed import seed_defaults

    configure_engine(settings=test_settings)
    init_db()
    with get_session_factory()() as session:
        seed_defaults(session, settings=test_settings)

    captured: dict = {}

    class FakeChat:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChat)
    monkeypatch.setattr(
        "app.core.llm.get_langfuse_handler", lambda: "langfuse-handler"
    )

    LLMService(get_session_factory(), settings=test_settings).build_model("writing")
    assert "langfuse-handler" in captured["callbacks"]

    captured.clear()
    monkeypatch.setattr("app.core.llm.get_langfuse_handler", lambda: None)
    LLMService(get_session_factory(), settings=test_settings).build_model("writing")
    assert "langfuse-handler" not in captured["callbacks"]


def test_workflow_emits_run_and_stage_spans(client_env, article_factory, monkeypatch):
    @contextmanager
    def fake_propagate(**_kwargs):
        yield

    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)
    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)

    article_id = article_factory()
    run = client_env.runner.start_run(article_id)
    client_env.runner.execute_sync(run.id, initial=True)

    by_name = {call["name"]: call for call in client.calls}
    assert "workflow.run" in by_name
    assert "stage.topic_selection" in by_name
    assert by_name["stage.topic_selection"]["metadata"]["run_id"] == run.id
    assert by_name["stage.topic_selection"]["metadata"]["article_id"] == article_id
    assert by_name["stage.topic_selection"]["metadata"]["stage"] == "topic_selection"
    assert by_name["workflow.run"]["metadata"]["run_id"] == run.id


def test_lifespan_configures_and_shuts_down_tracing(test_settings, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main_module

    calls: list[str] = []
    monkeypatch.setattr(
        main_module, "configure_tracing", lambda _settings: calls.append("start")
    )
    monkeypatch.setattr(main_module, "shutdown_tracing", lambda: calls.append("stop"))

    app = main_module.create_app(test_settings, start_scheduler=False)
    with TestClient(app):
        pass

    assert calls == ["start", "stop"]


def test_deep_agent_tools_emit_spans(monkeypatch):
    import deepagents

    from app.article_generation.research import deep_agent as deep_module
    from app.article_generation.research.deep_agent import DeepResearchRunner
    from app.schemas.artifacts import ResearchOutput
    from tests.fakes import FakeSearchTool, sample_results

    tools: dict = {}

    def fake_create_deep_agent(**kwargs):
        for item in kwargs["tools"]:
            tools[item.name] = item
        return object()

    class FakeFetcher:
        def fetch(self, url: str) -> str:
            return f"content of {url}"

    class LLM:
        def build_model(self, stage):  # noqa: ANN001
            return object()

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        deep_module,
        "run_with_budget",
        lambda *args, **kwargs: {
            "structured_response": ResearchOutput(facts=[])
        },
    )
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)

    runner = DeepResearchRunner(
        LLM(), FakeSearchTool(results=sample_results()), fetcher=FakeFetcher()
    )
    runner.run("选题", limit=2)

    tools["web_search"].invoke({"query": "AI 工程", "max_results": 2})
    tools["fetch_url"].invoke({"url": "https://example.com/a"})
    tools["save_source"].invoke({"title": "示例", "url": "https://example.com/a"})
    tools["save_source"].invoke({"title": "坏来源", "url": "ftp://example.com"})

    by_name = {call["name"]: index for index, call in enumerate(client.calls)}
    assert client.calls[by_name["tool.web_search"]]["metadata"] == {"tool": "web_search"}
    assert client.calls[by_name["tool.web_search"]]["input"] == {
        "query": "AI 工程",
        "max_results": 2,
    }
    assert client.calls[by_name["tool.fetch_url"]]["input"] == {
        "url": "https://example.com/a"
    }
    assert client.spans[by_name["tool.web_search"]].updates == [{"output": {"count": 2}}]
    assert client.spans[by_name["tool.fetch_url"]].updates == [
        {"output": {"chars": len("content of https://example.com/a")}}
    ]
    saved = [
        span.updates
        for call, span in zip(client.calls, client.spans)
        if call["name"] == "tool.save_source"
    ]
    assert saved == [
        [{"output": {"saved": True, "total": 1}}],
        [{"output": {"saved": False, "reason": "invalid_url"}}],
    ]


def test_source_fetch_span_records_status(monkeypatch):
    from app.article_generation.topic_selection.sources import collector
    from app.article_generation.topic_selection.sources.base import HotSignal
    from app.core.config import HotSourceSpec

    class Response:
        text = "feed"
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, **_kwargs):
        if "broken" in url:
            raise RuntimeError("boom")
        return Response()

    monkeypatch.setattr(collector.httpx, "get", fake_get)
    monkeypatch.setattr(
        collector,
        "parse_feed",
        lambda *_args, **_kwargs: [HotSignal(title="标题", source="正常源")],
    )
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)

    source = collector.HotTopicSource(
        specs=[
            HotSourceSpec(name="正常源", kind="rss", url="https://example.com/feed"),
            HotSourceSpec(name="坏源", kind="rss", url="https://broken.example/feed"),
        ]
    )
    assert [signal.title for signal in source.fetch(limit=5)] == ["标题"]

    by_source = {call["metadata"]["source"]: (call, span) for call, span in zip(
        client.calls, client.spans
    )}
    ok_call, ok_span = by_source["正常源"]
    assert ok_call["input"] == {"source": "正常源", "url": "https://example.com/feed"}
    assert ok_span.updates == [
        {"output": {"source": "正常源", "status": "ok", "count": 1, "relevant_count": 1}}
    ]
    err_call, err_span = by_source["坏源"]
    assert err_span.updates[0]["output"]["status"] == "error"
    assert err_span.updates[0]["level"] == "ERROR"


def test_fetch_url_span_records_success_and_failure(monkeypatch):
    from app.core import web

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html>hello</html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(web.UrlFetcher, "_robots_allowed", lambda *_args: True)
    monkeypatch.setattr(web.httpx, "get", lambda *_args, **_kwargs: Response())
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)

    body = web.UrlFetcher(max_bytes=10).fetch("https://example.com/a")
    assert body == "<html>hell"
    assert client.spans[0].updates == [
        {
            "output": {
                "url": "https://example.com/a",
                "status": 200,
                "chars": 10,
                "truncated": True,
            }
        }
    ]

    class BrokenResponse(Response):
        def raise_for_status(self) -> None:
            raise RuntimeError("404")

    monkeypatch.setattr(
        web.httpx, "get", lambda *_args, **_kwargs: BrokenResponse()
    )
    with pytest.raises(RuntimeError):
        web.UrlFetcher().fetch("https://example.com/b")
    assert client.spans[1].updates[0]["output"]["status"] == "error"
    assert client.spans[1].updates[0]["level"] == "ERROR"


def test_search_span_records_count_and_error(monkeypatch):
    from app.article_generation.research import tools

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"results": [{"title": "t", "url": "https://example.com/1"}]}

    monkeypatch.setattr(tools.httpx, "get", lambda *_args, **_kwargs: Response())
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)

    settings = _settings(search_endpoint="http://search.internal/api")
    results = tools.HttpSearchTool(settings=settings).search("AI", limit=3)
    assert [item.url for item in results] == ["https://example.com/1"]
    assert client.calls[0]["input"] == {"query": "AI", "limit": 3}
    assert client.spans[0].updates == [
        {"output": {"status": "ok", "count": 1, "engines": ["endpoint"]}}
    ]

    with pytest.raises(tools.SearchUnavailable):
        tools.HttpSearchTool(settings=_settings(search_endpoint="")).search("AI")
    assert client.spans[1].updates[0]["output"]["status"] == "error"


def test_publish_span_excludes_credentials():
    from app.article_generation.publishing.service import PublishingService

    class Adapter:
        def publish(self, artifact, credentials):
            from types import SimpleNamespace

            assert credentials == {"token": "secret"}
            return SimpleNamespace(status="published", success=True, remote_id="r1")

    client = FakeClient()
    tracing._client = client
    try:
        result = PublishingService._publish_adapter(
            Adapter(),
            object(),
            {"token": "secret"},
            platform="mock",
            article_id="a1",
            attempt=2,
        )
    finally:
        tracing._client = None

    assert result.remote_id == "r1"
    call = client.calls[0]
    assert call["input"] == {"platform": "mock", "article_id": "a1"}
    assert call["metadata"] == {"platform": "mock", "attempt": 2}
    assert "secret" not in repr(call)
    assert client.spans[0].updates == [
        {"output": {"status": "published", "success": True, "remote_id": "r1"}}
    ]


def test_run_with_budget_propagates_contextvars():
    import contextvars

    from app.core.budget import run_with_budget

    probe = contextvars.ContextVar("probe", default="missing")
    seen: dict = {}

    class Agent:
        def invoke(self, payload, config):  # noqa: ANN001
            seen["value"] = probe.get()
            return {}

    probe.set("workflow")
    run_with_budget(Agent(), {})
    assert seen["value"] == "workflow"


def test_shutdown_is_bounded_and_resets_state(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(tracing, "_client", client)
    monkeypatch.setattr(tracing, "_handler", "handler")

    tracing.shutdown_tracing(0.5)

    assert client.closed is True
    assert tracing.tracing_enabled() is False
    assert tracing.get_langfuse_handler() is None
