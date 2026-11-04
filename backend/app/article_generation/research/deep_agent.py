"""deepagents-backed research agent with search/fetch tools and a token budget."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.article_generation.research.tools import SearchResult, UrlFetcher
from app.core.budget import run_with_budget
from app.core.llm import LLMService, parse_json_payload
from app.core.constants import Stage
from app.core.tracing import trace_span
from app.schemas.artifacts import ExtractedSource, ResearchOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是严谨的资料研究员。围绕给定选题：
1. 先列出 3-5 个决定文章质量的关键问题（数据、机制、反例、最新进展），再逐条用 web_search 验证；中英文关键词各尝试一次，避免只搜一个说法。
2. 搜索结果只有标题和摘要时，用 fetch_url 阅读最关键的 2-3 个页面，核对原文中的数字、时间和结论。
3. 优先一手来源：官方文档、论文、政府/标准组织、维护者公告；媒体转述只作补充。不同来源冲突时记录冲突，不要强行合并。
4. 只使用工具返回的真实来源，禁止编造 URL、数字或时间。save_source 只保存真正支撑事实的来源。
5. 最后按 schema 提交 sources 与 facts。事实要原子化、可验证；source_index 使用 sources 数组的 1-based 序号，无法核实的要点标记为 0。
6. 来源足够（通常 3-6 条高质量来源即可）就停止搜索，不要为了凑数反复调用工具。
7. 如果搜索结果不足、时效过旧或相互矛盾，设置 low_confidence=true 并在 notes 中说明缺口。"""


class DeepResearchRunner:
    """Runs a bounded deep agent and returns a validated ``ResearchOutput``."""

    def __init__(
        self,
        llm: LLMService,
        search_tool: Any,
        *,
        fetcher: UrlFetcher | None = None,
        max_steps: int = 8,
        timeout_seconds: float = 120.0,
        max_tokens: int = 30_000,
    ) -> None:
        self.llm = llm
        self.search_tool = search_tool
        self.fetcher = fetcher or UrlFetcher()
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens

    def run(
        self,
        topic_title: str,
        topic_angle: str = "",
        *,
        limit: int = 8,
        system_prompt: str | None = None,
        feedback: str | None = None,
    ) -> ResearchOutput:
        from deepagents import create_deep_agent

        saved: list[ExtractedSource] = []
        cancelled = threading.Event()

        @tool
        def web_search(query: str, max_results: int = 8) -> str:
            """Search the web for a query. Returns JSON records with title, url and snippet."""
            if cancelled.is_set():
                return "研究已取消，请直接提交已有结果。"
            with trace_span(
                "tool.web_search",
                input={"query": query, "max_results": max_results},
                metadata={"tool": "web_search"},
            ) as span:
                try:
                    results = self.search_tool.search(query, limit=min(max_results, limit))
                except Exception as exc:  # noqa: BLE001 - let the agent try another query
                    if span is not None:
                        span.update(output={"error": str(exc)}, level="ERROR")
                    return f"搜索失败: {exc}；请调整关键词或改用其他来源。"
                payload = json.dumps(
                    [
                        {
                            "title": item.title,
                            "url": item.url,
                            "snippet": item.snippet,
                            "published_at": item.published_at,
                        }
                        for item in results
                    ],
                    ensure_ascii=False,
                )
                if span is not None:
                    span.update(output={"count": len(results)})
                return payload

        @tool
        def fetch_url(url: str) -> str:
            """Fetch a public URL as text. Respects robots.txt and truncates long pages."""
            if cancelled.is_set():
                return "研究已取消，请直接提交已有结果。"
            with trace_span(
                "tool.fetch_url",
                input={"url": url},
                metadata={"tool": "fetch_url"},
            ) as span:
                try:
                    text = self.fetcher.fetch(url)
                except Exception as exc:  # noqa: BLE001 - never kill the whole run
                    if span is not None:
                        span.update(output={"error": str(exc)}, level="ERROR")
                    return f"抓取失败: {exc}；可改读其他来源。"
                if span is not None:
                    span.update(output={"chars": len(text)})
                return text

        @tool
        def save_source(title: str, url: str, snippet: str = "") -> str:
            """Save a source that supports a fact. Call this for every source you rely on."""
            with trace_span(
                "tool.save_source",
                input={"title": title, "url": url},
                metadata={"tool": "save_source"},
            ) as span:
                if not url.lower().startswith(("http://", "https://")):
                    if span is not None:
                        span.update(output={"saved": False, "reason": "invalid_url"})
                    return "来源 URL 必须以 http(s) 开头"
                if all(item.url != url for item in saved):
                    saved.append(
                        ExtractedSource(
                            title=title or url, url=url, snippet=snippet[:1000]
                        )
                    )
                if span is not None:
                    span.update(output={"saved": True, "total": len(saved)})
                return f"saved ({len(saved)} sources)"

        model = self.llm.build_model(Stage.RESEARCH)
        agent = create_deep_agent(
            model=model,
            tools=[web_search, fetch_url, save_source],
            system_prompt=system_prompt or SYSTEM_PROMPT,
            response_format=ResearchOutput,
        )
        question = (
            f"选题：{topic_title}\n角度：{topic_angle or '未指定'}\n"
            f"最多使用 {limit} 条外部来源。请调研并提交结构化结果。"
        )
        if feedback:
            question += f"\n人工驳回意见（必须落实）：{feedback}"
        result = run_with_budget(
            agent,
            {"messages": [HumanMessage(content=question)]},
            max_steps=self.max_steps,
            timeout_seconds=self.timeout_seconds,
            max_tokens=self.max_tokens,
            cancel_event=cancelled,
        )
        output = self._structured(result)
        if not output.sources and saved:
            output = output.model_copy(update={"sources": saved})
        return output

    @staticmethod
    def _structured(result: Any) -> ResearchOutput:
        structured = None
        if isinstance(result, dict):
            structured = result.get("structured_response")
        else:
            structured = getattr(result, "structured_response", None)
        if isinstance(structured, ResearchOutput):
            return structured
        if isinstance(structured, dict):
            return ResearchOutput.model_validate(structured)
        if structured is not None:
            return ResearchOutput.model_validate(structured)
        # Last resort: the final agent message may contain a JSON object.
        messages = result.get("messages", []) if isinstance(result, dict) else []
        content = getattr(messages[-1], "content", "") if messages else ""
        if content:
            return ResearchOutput.model_validate(parse_json_payload(content))
        raise ValueError("deep agent 未返回结构化研究结果")


def sources_from_output(output: ResearchOutput) -> list[SearchResult]:
    return [
        SearchResult(
            title=item.title,
            url=item.url,
            snippet=item.snippet,
            published_at=item.published_at,
        )
        for item in output.sources
    ]
