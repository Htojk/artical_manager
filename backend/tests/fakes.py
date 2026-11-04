"""Deterministic fakes used across the test suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.article_generation.research.tools import SearchResult
from app.schemas.artifacts import (
    DraftOutput,
    EvolvingSuggestion,
    EvolvingSuggestions,
    ExtractedFact,
    OutlineOutput,
    OutlineSection,
    ResearchOutput,
    ReviewDimension,
    ReviewIssue,
    ReviewOutput,
    RevisedSection,
    TargetedRevisionOutput,
    TitleCandidate,
    TitleOptimizationOutput,
    TopicCandidate,
    TopicCandidates,
)

DIMENSIONS = ("fact", "structure", "readability", "compliance", "originality")


@dataclass
class FakeController:
    topic_titles: list[str] = field(default_factory=lambda: [f"候选选题{i}：AI 工程实践" for i in range(5)])
    review_plan: list[dict[str, Any]] = field(default_factory=list)
    review_calls: int = 0
    draft_calls: int = 0
    outline_calls: int = 0
    research_calls: int = 0
    low_confidence: bool = False
    suggestions: list[EvolvingSuggestion] = field(default_factory=list)
    targeted_sections: list[tuple[str, str]] = field(
        default_factory=lambda: [("第二节 结论", "定向修订后的结论段落。")]
    )
    on_research: Callable[[], None] | None = None
    on_outline: Callable[[], None] | None = None
    on_draft: Callable[[], None] | None = None

    def review_scores(self) -> dict[str, Any]:
        index = min(self.review_calls, len(self.review_plan) - 1) if self.review_plan else -1
        self.review_calls += 1
        if self.review_plan and index >= 0:
            plan = self.review_plan[index]
            return plan
        return {name: 90 for name in DIMENSIONS}

    def review_output(self) -> ReviewOutput:
        plan = self.review_scores()
        critical = set(plan.get("_critical", []))
        locations = plan.get("_locations", {})
        dimensions = []
        for name in DIMENSIONS:
            issues = []
            if name in critical:
                issues.append(
                    ReviewIssue(
                        location=locations.get(name, "正文"),
                        description=f"{name} 存在关键问题",
                        severity="critical",
                    )
                )
            dimensions.append(
                ReviewDimension(
                    dimension=name,
                    score=float(plan.get(name, 90)),
                    issues=issues,
                    suggestions=[],
                )
            )
        return ReviewOutput(dimensions=dimensions, summary="假模型审核结果")


class FakeStructured:
    def __init__(self, schema: type, controller: FakeController) -> None:
        self.schema = schema
        self.controller = controller

    def invoke(self, _messages: Any) -> Any:
        schema = self.schema
        controller = self.controller
        if schema is TopicCandidates:
            return TopicCandidates(
                candidates=[
                    TopicCandidate(
                        title=title,
                        angle="从工程实践与成本角度展开分析",
                        rationale="有真实的读者需求与讨论热度",
                        target_platforms=["mock"],
                        hot_signal_index=index,
                        discussion_score=80,
                        discussion_reason="存在真实利益相关方与对立观点",
                    )
                    for index, title in enumerate(controller.topic_titles, start=1)
                ]
            )
        if schema is ResearchOutput:
            controller.research_calls += 1
            if controller.on_research is not None:
                controller.on_research()
            return ResearchOutput(
                facts=[ExtractedFact(statement="可验证的事实要点", source_index=1)],
                low_confidence=controller.low_confidence,
            )
        if schema is OutlineOutput:
            controller.outline_calls += 1
            if controller.on_outline is not None:
                controller.on_outline()
            return OutlineOutput(
                title="测试文章标题",
                hook="一个反常识的开场判断",
                sections=[
                    OutlineSection(
                        heading="第一节 背景",
                        key_points=["关键背景"],
                        source_refs=[1],
                    ),
                    OutlineSection(heading="第二节 结论", key_points=["可执行建议"]),
                ],
                target_words=1500,
                summary="测试大纲",
                tags=["AI", "工程"],
            )
        if schema is DraftOutput:
            controller.draft_calls += 1
            if controller.on_draft is not None:
                controller.on_draft()
            return DraftOutput(
                title="测试文章标题",
                summary="这是一篇测试文章的摘要",
                content_md=(
                    "# 测试文章标题\n\n"
                    "## 第一节 背景\n\n"
                    "这是第一段正文，引用来源 [1]。\n\n"
                    "## 第二节 结论\n\n"
                    "这是第二段正文，给出可执行建议。\n"
                ),
                tags=["AI", "工程"],
            )
        if schema is TargetedRevisionOutput:
            return TargetedRevisionOutput(
                sections=[
                    RevisedSection(heading=heading, content_md=body)
                    for heading, body in controller.targeted_sections
                ],
                summary="定向修订摘要",
                tags=["AI", "工程"],
            )
        if schema is TitleOptimizationOutput:
            return TitleOptimizationOutput(
                candidates=[
                    TitleCandidate(
                        title="测试标题：AI 工程实践的三条经验",
                        style="干货型",
                        rationale="点出读者收益",
                        score=92,
                    ),
                    TitleCandidate(
                        title="为什么你的 AI 项目总是延期？",
                        style="悬念型",
                        rationale="制造疑问",
                        score=85,
                    ),
                    TitleCandidate(
                        title="AI 工程实践：从踩坑到落地",
                        style="对比型",
                        rationale="前后对比清晰",
                        score=80,
                    ),
                ],
                recommended="测试标题：AI 工程实践的三条经验",
                strategy="以读者收益为核心，配合悬念与对比",
            )
        if schema is ReviewOutput:
            return controller.review_output()
        if schema is EvolvingSuggestions:
            return EvolvingSuggestions(suggestions=controller.suggestions)
        raise AssertionError(f"unexpected schema: {schema}")


class FakeModel:
    def __init__(self, controller: FakeController) -> None:
        self.controller = controller

    def with_structured_output(self, schema: type) -> FakeStructured:
        return FakeStructured(schema, self.controller)

    def invoke(self, _messages: Any) -> Any:
        class Response:
            content = "{}"

        return Response()


def fake_model_factory(controller: FakeController):
    def factory(_stage: str) -> FakeModel:
        return FakeModel(controller)

    return factory


@dataclass
class FakeSearchTool:
    results: list[SearchResult] = field(default_factory=list)
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return self.results[:limit]


def sample_results() -> list[SearchResult]:
    return [
        SearchResult(
            title="OpenAI 官方文档",
            url="https://platform.openai.com/docs/overview",
            snippet="API 使用的官方说明",
        ),
        SearchResult(
            title="重复链接",
            url="https://platform.openai.com/docs/overview/",
            snippet="重复内容",
        ),
        SearchResult(
            title="技术社区讨论",
            url="https://example.com/post/1",
            snippet="社区经验",
        ),
    ]
