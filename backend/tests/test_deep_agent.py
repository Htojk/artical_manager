"""Deep-agent budget accounting and research runner behaviour."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.article_generation.research import deep_agent as deep_module
from app.article_generation.research.deep_agent import DeepResearchRunner
from app.article_generation.research.service import ResearchService
from app.core.budget import BudgetCallback, TokenBudget, run_with_budget
from app.core.errors import BudgetExceededError
from app.schemas.artifacts import ExtractedFact, ExtractedSource, ResearchOutput
from tests.fakes import FakeSearchTool


class FakeDeepAgent:
    def __init__(self, output: ResearchOutput | None = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    def run(self, topic_title: str, topic_angle: str = "", *, limit: int = 8) -> ResearchOutput:
        self.calls.append((topic_title, topic_angle, limit))
        if self.error is not None:
            raise self.error
        assert self.output is not None
        return self.output


def _deep_output() -> ResearchOutput:
    return ResearchOutput(
        sources=[
            ExtractedSource(title="官方文档", url="https://docs.python.org/3/"),
            ExtractedSource(title="重复链接", url="https://docs.python.org/3"),
        ],
        facts=[
            ExtractedFact(statement="Python 3 文档事实", source_index=2),
            ExtractedFact(statement="没有来源的推断", source_index=0),
        ],
        notes="补充说明",
    )


def test_research_service_uses_deep_agent_and_maps_deduped_indices(article_factory):
    article_id = article_factory()
    from app.core.db import get_session_factory

    session = get_session_factory()()
    try:
        deep = FakeDeepAgent(_deep_output())
        service = ResearchService(
            session, None, search_tool=FakeSearchTool(), deep_agent=deep  # type: ignore[arg-type]
        )
        result = service.run(article_id)
        sources = service.list_sources(article_id)
        facts = service.list_facts(article_id)
        assert deep.calls == [("测试选题：AI 工程实践", "工程实践", 8)]
        assert len(sources) == 1
        assert [fact.statement for fact in facts] == [
            "Python 3 文档事实",
            "没有来源的推断",
        ]
        assert facts[0].source_id == sources[0].id
        assert facts[1].source_id is None
        assert facts[1].status == "unverified"
        assert result.source_count == 1
        assert result.fact_count == 2
        assert "补充说明" in result.errors
    finally:
        session.close()


def test_research_service_falls_back_when_deep_agent_fails(article_factory):
    article_id = article_factory()
    from app.core.db import get_session_factory
    from tests.fakes import FakeController, FakeSearchTool, fake_model_factory
    from app.core.llm import LLMService

    session_factory = get_session_factory()
    session = session_factory()
    try:
        controller = FakeController()
        llm = LLMService(
            session_factory,
            settings=None,
            model_factory=fake_model_factory(controller),
        )
        search_tool = FakeSearchTool(results=[], error=None)
        service = ResearchService(
            session,
            llm,
            search_tool=search_tool,
            deep_agent=FakeDeepAgent(error=RuntimeError("agent boom")),
        )
        result = service.run(article_id)
        assert search_tool.calls, "fallback should call the plain search tool"
        assert result.source_count == 0
        assert result.low_confidence is True
        assert any("deep agent" in item for item in result.errors)
    finally:
        session.close()


def test_token_budget_raises_on_token_overflow():
    budget = TokenBudget(max_tokens=100, max_steps=5)
    budget.add_usage(40, 20)
    assert budget.total_tokens == 60
    with pytest.raises(BudgetExceededError):
        budget.add_usage(30, 30)
    assert budget.as_dict()["total_tokens"] == 120


def test_token_budget_raises_on_step_overflow():
    budget = TokenBudget(max_tokens=1000, max_steps=2)
    budget.add_step()
    budget.add_step()
    with pytest.raises(BudgetExceededError):
        budget.add_step()


def test_budget_callback_records_llm_usage():
    budget = TokenBudget(max_tokens=1000, max_steps=5)
    callback = BudgetCallback(budget)
    response = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 12, "completion_tokens": 8}},
        generations=[],
    )
    callback.on_llm_end(response)
    callback.on_tool_start({"name": "web_search"}, "q")
    assert (budget.prompt_tokens, budget.completion_tokens, budget.steps) == (12, 8, 1)


def test_budget_callback_ignores_missing_usage():
    budget = TokenBudget(max_tokens=1000, max_steps=5)
    BudgetCallback(budget).on_llm_end(SimpleNamespace(llm_output={}, generations=[]))
    assert budget.total_tokens == 0


def test_run_with_budget_passes_limits_and_returns_result():
    seen: dict = {}

    class Agent:
        def invoke(self, payload, config):  # noqa: ANN001
            seen["payload"] = payload
            seen["config"] = config
            return {"ok": True}

    result = run_with_budget(Agent(), {"messages": []}, max_steps=3)
    assert result == {"ok": True}
    assert seen["config"]["recursion_limit"] == 8
    assert isinstance(seen["config"]["callbacks"][0], BudgetCallback)


def test_budget_callback_sets_cancel_event_on_token_overflow():
    event = threading.Event()
    callback = BudgetCallback(
        TokenBudget(max_tokens=10, max_steps=5), cancel_event=event
    )
    response = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 20, "completion_tokens": 0}},
        generations=[],
    )
    with pytest.raises(BudgetExceededError):
        callback.on_llm_end(response)
    assert event.is_set()


def test_budget_callback_sets_cancel_event_on_step_overflow():
    event = threading.Event()
    callback = BudgetCallback(
        TokenBudget(max_tokens=1000, max_steps=1), cancel_event=event
    )
    callback.on_tool_start({"name": "web_search"}, "q")
    with pytest.raises(BudgetExceededError):
        callback.on_tool_start({"name": "web_search"}, "q")
    assert event.is_set()


def test_run_with_budget_timeout_sets_cancel_event():
    event = threading.Event()

    class SlowAgent:
        def invoke(self, payload, config):  # noqa: ANN001
            time.sleep(0.5)
            return {}

    with pytest.raises(BudgetExceededError, match="超时"):
        run_with_budget(SlowAgent(), {}, timeout_seconds=0.05, cancel_event=event)
    assert event.is_set()


def test_research_service_keeps_sources_when_extraction_fails(article_factory):
    article_id = article_factory()
    from app.core.db import get_session_factory
    from tests.fakes import sample_results

    class BrokenLLM:
        def structured(self, **kwargs):  # noqa: ANN003
            raise TimeoutError("extraction budget exhausted")

    session = get_session_factory()()
    try:
        service = ResearchService(
            session, BrokenLLM(), search_tool=FakeSearchTool(results=sample_results())
        )
        result = service.run(article_id)
        assert result.source_count == 2
        assert result.low_confidence is True
        assert any("事实提取失败" in item for item in result.errors)
        assert service.list_sources(article_id)
    finally:
        session.close()


def test_run_with_budget_timeout_raises():
    class SlowAgent:
        def invoke(self, payload, config):  # noqa: ANN001
            time.sleep(0.5)
            return {}

    with pytest.raises(BudgetExceededError, match="超时"):
        run_with_budget(SlowAgent(), {}, timeout_seconds=0.05)


def test_run_with_budget_rejects_invalid_limits():
    with pytest.raises(ValueError):
        run_with_budget(object(), {}, max_steps=0)
    with pytest.raises(ValueError):
        run_with_budget(object(), {}, max_tokens=0)


def test_deep_runner_builds_agent_and_merges_saved_sources(monkeypatch):
    captured: dict = {}
    saved_tool: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        for item in kwargs["tools"]:
            if item.name == "save_source":
                saved_tool["tool"] = item
        return object()

    def fake_run_with_budget(agent, payload, **kwargs):
        saved_tool["tool"].invoke(
            {"title": "手动记录", "url": "https://example.com/a", "snippet": "摘要"}
        )
        return {"structured_response": ResearchOutput(facts=[ExtractedFact(statement="事实")])}

    import deepagents

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(deep_module, "run_with_budget", fake_run_with_budget)

    class LLM:
        def build_model(self, stage):  # noqa: ANN001
            captured["stage"] = stage
            return object()

    runner = DeepResearchRunner(LLM(), FakeSearchTool(), max_steps=4, max_tokens=5000)
    output = runner.run("选题", "角度", limit=3)
    assert captured["response_format"] is ResearchOutput
    assert captured["stage"] == "research"
    assert [item.url for item in output.sources] == ["https://example.com/a"]


def test_deep_runner_rejects_non_http_saved_source(monkeypatch):
    saved_tool: dict = {}

    def fake_create_deep_agent(**kwargs):
        for item in kwargs["tools"]:
            if item.name == "save_source":
                saved_tool["tool"] = item
        return object()

    import deepagents

    monkeypatch.setattr(deepagents, "create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(
        deep_module,
        "run_with_budget",
        lambda *args, **kwargs: {
            "structured_response": ResearchOutput(
                sources=[ExtractedSource(title="坏来源", url="ftp://x")]
            )
        },
    )

    class LLM:
        def build_model(self, stage):  # noqa: ANN001
            return object()

    runner = DeepResearchRunner(LLM(), FakeSearchTool())
    output = runner.run("选题")
    assert output.sources[0].url == "ftp://x"
    message = saved_tool["tool"].invoke({"title": "坏来源", "url": "ftp://x"})
    assert "http" in message


def test_deep_runner_structured_fallbacks():
    assert DeepResearchRunner._structured(
        {"structured_response": ResearchOutput(facts=[])}
    ) == ResearchOutput(facts=[])

    class Message:
        content = '{"facts": [{"statement": "x", "source_index": 0}], "sources": []}'

    parsed = DeepResearchRunner._structured({"messages": [Message()]})
    assert parsed.facts[0].statement == "x"

    with pytest.raises(ValueError, match="结构化"):
        DeepResearchRunner._structured({"messages": []})
