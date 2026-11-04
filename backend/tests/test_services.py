"""Stage service behavior: topic, research, outline, writing, review, format, publish."""

from __future__ import annotations

import pytest

from app.article_generation.formatting.service import FormattingService
from app.article_generation.outline.service import OutlineService
from app.article_generation.publishing.service import PublishingService
from app.article_generation.research.service import ResearchService, assess_credibility, normalize_url
from app.article_generation.review.routing import compute_total, determine_rollback
from app.article_generation.review.service import ReviewService
from app.article_generation.title_optimization.service import TitleOptimizationService
from app.article_generation.topic_selection.service import TopicService
from app.article_generation.writing.service import WritingService, count_words
from app.core.constants import ArticleStatus, PublishStatus, Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.security import CredentialCipher, CredentialService
from app.models.article import (
    Article,
    DraftVersion,
    Fact,
    PublishRecord,
    ReviewReport,
    Source,
    Topic,
)
from app.schemas.artifacts import TitleCandidate
from app.models.llm import LLMCall
from app.platforms.base import (
    AdapterAvailability,
    ArticleForFormat,
    FormatResult,
    PlatformAdapter,
    PublishResult,
)
from app.skills.manager import SkillManager
from tests.fakes import FakeSearchTool, sample_results


def _session(client_env):
    return client_env.session_factory()


class RecordingLLM:
    """Delegate to the fake LLM while capturing the system prompt of each call."""

    def __init__(self, inner):
        self.inner = inner
        self.systems: list[str] = []

    def structured(self, **kwargs):
        self.systems.append(kwargs.get("system", ""))
        return self.inner.structured(**kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class EmptyHotSource:
    errors: list[str] = []

    def fetch(self):
        return []


def _article(session, *, platforms=None, confirmation=False):
    article = Article(
        target_platforms=platforms or ["mock"],
        publish_confirmation=confirmation,
        topic_mode="manual",
    )
    session.add(article)
    session.commit()
    return article


def test_topic_manual_and_select(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article.id, title="手动选题", angle="角度")
        assert article.title == "手动选题"
        assert service.list_topics(article.id) == [topic]
        selection = service.select(article.id, topic.id)
        assert selection.topic.selected
        assert selection.source_fetch.ok is False
        assert article.current_topic_id == topic.id
        assert service.selected_topic(article.id).id == topic.id
        with pytest.raises(ValidationError):
            service.create_manual(article.id, title="  ")


def test_topic_recommend_returns_five(client_env):
    with _session(client_env) as session:
        article = _article(session)

        class NoHot:
            errors: list[str] = []

            def fetch(self):
                return []

        service = TopicService(session, client_env.llm, hot_source=NoHot())
        result = service.recommend(article.id, domain="AI")
        assert len(result.topics) == 5
        assert result.fallback_used
        assert all(topic.source == "ai" for topic in result.topics)

        with pytest.raises(ValidationError):
            service.recommend(article.id, count=3)

        titles = [topic.title for topic in result.topics]
        with pytest.raises(ValidationError):
            service.recommend(article.id, exclude_titles=titles)


def test_topic_recommend_replaces_low_discussion_candidates(client_env):
    from app.schemas.artifacts import TopicCandidate, TopicCandidates

    class QueueLLM:
        def __init__(self) -> None:
            self.calls = 0

        def structured(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return TopicCandidates(
                    candidates=[
                        TopicCandidate(
                            title=f"低讨论候选{i}",
                            angle="正确的废话角度",
                            rationale="讨论度不足",
                            discussion_score=30,
                        )
                        for i in range(5)
                    ]
                )
            return TopicCandidates(
                candidates=[
                    TopicCandidate(
                        title=f"高讨论候选{i}",
                        angle="存在对立观点",
                        rationale="有真实利益相关方",
                        hot_signal_index=0,
                        discussion_score=85,
                        discussion_reason="谁和谁在争什么",
                    )
                    for i in range(5)
                ]
            )

    class NoHot:
        errors: list[str] = []

        def fetch(self):
            return []

    llm = QueueLLM()
    with _session(client_env) as session:
        article = _article(session)
        result = TopicService(session, llm, hot_source=NoHot()).recommend(article.id)

    assert llm.calls == 2
    assert len(result.topics) == 5
    assert all(topic.title.startswith("高讨论候选") for topic in result.topics)
    assert all(topic.discussion_score == 85 for topic in result.topics)


def test_topic_recommend_fails_when_discussion_stays_low(client_env):
    from app.schemas.artifacts import TopicCandidate, TopicCandidates

    class LowLLM:
        def __init__(self) -> None:
            self.calls = 0

        def structured(self, **_kwargs):
            self.calls += 1
            return TopicCandidates(
                candidates=[
                    TopicCandidate(
                        title=f"低讨论候选{self.calls}-{i}",
                        angle="正确的废话角度",
                        rationale="讨论度不足",
                        discussion_score=20,
                    )
                    for i in range(5)
                ]
            )

    class NoHot:
        errors: list[str] = []

        def fetch(self):
            return []

    llm = LowLLM()
    with _session(client_env) as session:
        article = _article(session)
        with pytest.raises(ValidationError):
            TopicService(session, llm, hot_source=NoHot()).recommend(article.id)

    assert llm.calls == 3


def test_topic_recommend_links_each_candidate_to_its_signal(client_env):
    from app.article_generation.topic_selection.sources import HotSignal
    from app.schemas.artifacts import TopicCandidate, TopicCandidates

    signals = [
        HotSignal(title="信号一", source="源", url="https://a.example/1", index=1),
        HotSignal(title="信号二", source="源", url="https://a.example/2", index=2),
    ]

    class SignalSource:
        errors: list[str] = []

        def fetch(self):
            return signals

    class IndexLLM:
        def structured(self, **_kwargs):
            return TopicCandidates(
                candidates=[
                    TopicCandidate(
                        title=f"候选选题{i}号",
                        angle="从冲突线切入",
                        rationale="有讨论空间",
                        hot_signal_index=signal_index,
                        discussion_score=80,
                    )
                    for i, signal_index in enumerate([2, 1, 0, 2, 1], start=1)
                ]
            )

    with _session(client_env) as session:
        article = _article(session)
        result = TopicService(session, IndexLLM(), hot_source=SignalSource()).recommend(
            article.id
        )

    assert result.topics[0].hot_signals[0]["title"] == "信号二"
    assert result.topics[1].hot_signals[0]["title"] == "信号一"
    assert result.topics[2].hot_signals == []
    assert result.topics[3].hot_signals[0]["url"] == "https://a.example/2"
    assert result.topics[4].hot_signals[0]["title"] == "信号一"


def test_topic_prompt_only_contains_title_level_signals(client_env):
    from app.article_generation.topic_selection.sources import HotSignal

    captured: dict = {}

    class SignalSource:
        errors: list[str] = []

        def fetch(self):
            return [
                HotSignal(
                    title="标题甲：某公司发布新模型",
                    source="示例源",
                    url="https://secret.example/should-not-leak",
                    published_at="2026-10-01",
                    index=1,
                )
            ]

    class RecordingLLM:
        def structured(self, **kwargs):
            captured.update(kwargs)
            return client_env.llm.structured(**kwargs)

    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, RecordingLLM(), hot_source=SignalSource())
        service.recommend(article.id, domain="AI")

    prompt = captured["user"]
    assert "标题甲：某公司发布新模型" in prompt
    assert "示例源" in prompt
    assert "2026-10-01" in prompt
    assert "secret.example" not in prompt
    assert "should-not-leak" not in prompt


def test_topic_candidate_normalizes_discussion_fields():
    from app.schemas.artifacts import TopicCandidate

    high = TopicCandidate(
        title="候选标题足够长",
        angle="从争议点切入",
        rationale="有真实利益相关方",
        hot_signal_index="2",
        discussion_score=120,
    )
    assert high.hot_signal_index == 2
    assert high.discussion_score == 100

    missing = TopicCandidate(
        title="缺少评分字段", angle="从工程实践切入", rationale="测试缺省值"
    )
    assert missing.hot_signal_index == 0
    assert missing.discussion_score == 0
    assert missing.discussion_reason == ""


class FakeContentFetcher:
    def __init__(self, text: str = "抓取到的文章正文", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[str] = []

    def fetch(self, url: str, content_selector: str = "") -> str:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        return self.text


def _topic_with_signal(session, article_id: str, url: str = "https://example.com/post/1"):
    service = TopicService(session, None)  # type: ignore[arg-type]
    topic = service.create_manual(article_id, title="关联热点的选题")
    topic.hot_signals = [
        {
            "title": "热点文章标题",
            "source": "示例源",
            "url": url,
            "published_at": "2026-10-01",
        }
    ]
    session.commit()
    return service, topic


def test_select_topic_fetches_linked_article(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service, topic = _topic_with_signal(session, article.id)
        fetcher = FakeContentFetcher("这是抓取到的完整正文。")

        selection = TopicService(
            session, client_env.llm, content_fetcher=fetcher
        ).select(article.id, topic.id)

        assert selection.source_fetch.ok
        assert selection.source_fetch.source_id
        source = session.get(Source, selection.source_fetch.source_id)
        assert source.added_by == "topic"
        assert source.snippet == "这是抓取到的完整正文。"
        assert source.url == "https://example.com/post/1"
        assert source.dedupe_key == "https://example.com/post/1"
        assert fetcher.calls == ["https://example.com/post/1"]


def test_select_topic_reuses_existing_source(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service, topic = _topic_with_signal(session, article.id)
        existing = Source(
            article_id=article.id,
            title="已存在的来源",
            url="https://example.com/post/1",
            dedupe_key="https://example.com/post/1",
            added_by="user",
        )
        session.add(existing)
        session.commit()
        fetcher = FakeContentFetcher(error=AssertionError("must not fetch"))

        selection = TopicService(
            session, client_env.llm, content_fetcher=fetcher
        ).select(article.id, topic.id)

        assert selection.source_fetch.ok
        assert selection.source_fetch.source_id == existing.id
        assert "已复用" in (selection.source_fetch.reason or "")
        assert fetcher.calls == []
        assert len([item for item in session.query(Source).all()]) == 1


def test_select_topic_survives_fetch_failure(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service, topic = _topic_with_signal(session, article.id)
        fetcher = FakeContentFetcher(error=PermissionError("robots.txt 不允许抓取"))

        selection = TopicService(
            session, client_env.llm, content_fetcher=fetcher
        ).select(article.id, topic.id)

        assert selection.topic.selected
        assert article.current_topic_id == topic.id
        assert selection.source_fetch.ok is False
        assert "robots.txt" in (selection.source_fetch.error or "")
        assert session.query(Source).count() == 0


def test_research_dedupes_and_links_facts(client_env):
    with _session(client_env) as session:
        article = _article(session)
        topic_service = TopicService(session, client_env.llm)
        topic = topic_service.create_manual(article.id, title="研究选题")
        topic_service.select(article.id, topic.id)

        service = ResearchService(
            session, client_env.llm, search_tool=FakeSearchTool(results=sample_results())
        )
        result = service.run(article.id)
        assert result.source_count == 2
        assert result.fact_count == 1
        assert not result.low_confidence
        facts = service.list_facts(article.id)
        assert facts[0].status == "verified"
        assert facts[0].source_id is not None

        again = service.run(article.id)
        assert again.source_count == 2
        assert again.fact_count == 1


def _add_topic_source(session, article_id: str, *, url: str, snippet: str) -> Source:
    source = Source(
        article_id=article_id,
        title="选题阶段预抓取来源",
        url=url,
        snippet=snippet,
        dedupe_key=normalize_url(url),
        added_by="topic",
    )
    session.add(source)
    session.commit()
    return source


def test_research_preserves_topic_prefetched_sources(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article.id, title="预抓取来源保留")
        service.select(article.id, topic.id)
        _add_topic_source(
            session,
            article.id,
            url="https://qbitai.example/post/keep",
            snippet="选题阶段抓取的正文。",
        )

        research = ResearchService(
            session, client_env.llm, search_tool=FakeSearchTool(results=sample_results())
        )
        research.run(article.id)
        assert any(source.added_by == "topic" for source in research.list_sources(article.id))

        research.run(article.id)
        kept = [
            source
            for source in research.list_sources(article.id)
            if source.added_by == "topic"
        ]
        assert len(kept) == 1


def test_research_reuses_prefetched_link_and_links_facts(client_env):
    prefetched_url = "https://platform.openai.com/docs/overview"
    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article.id, title="复用预抓取链接")
        service.select(article.id, topic.id)
        prefetched = _add_topic_source(
            session,
            article.id,
            url=prefetched_url,
            snippet="预抓取的官方文档正文。",
        )

        research = ResearchService(
            session, client_env.llm, search_tool=FakeSearchTool(results=sample_results())
        )
        result = research.run(article.id)

        sources = research.list_sources(article.id)
        assert len(sources) == 2
        assert len(
            [
                source
                for source in sources
                if source.dedupe_key == normalize_url(prefetched_url)
            ]
        ) == 1
        fact = research.list_facts(article.id)[0]
        assert fact.source_id == prefetched.id
        assert result.source_count == 2


def test_research_prompt_includes_prefetched_body(client_env):
    captured: dict = {}

    class RecordingPrompts:
        def render(self, name, **context):
            captured["name"] = name
            captured["context"] = context
            return "research prompt"

    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article.id, title="正文进入研究提示词")
        service.select(article.id, topic.id)
        _add_topic_source(
            session,
            article.id,
            url="https://qbitai.example/post/body",
            snippet="预抓取正文：模型发布了新的推理框架。",
        )

        ResearchService(
            session,
            client_env.llm,
            prompts=RecordingPrompts(),
            search_tool=FakeSearchTool(results=sample_results()),
        ).run(article.id)

    assert captured["name"] == "research.md"
    snippets = [source["snippet"] for source in captured["context"]["sources"]]
    assert "预抓取正文：模型发布了新的推理框架。" in snippets


def test_generation_prompts_render_human_feedback(client_env, article_factory):
    article_id = article_factory()
    feedback = "补充权威数据并调整章节顺序"
    rendered: dict[str, dict] = {}

    class RecordingPrompts:
        def render(self, name, **context):
            rendered[name] = context
            return name

    with _session(client_env) as session:
        ResearchService(
            session,
            client_env.llm,
            prompts=RecordingPrompts(),
            search_tool=FakeSearchTool(sample_results()),
            feedback=feedback,
        ).run(article_id)
        outline = OutlineService(
            session, client_env.llm, prompts=RecordingPrompts(), feedback=feedback
        )
        outline.generate(article_id)
        outline.revise(article_id, ["结构调整"])
        writing = WritingService(
            session,
            client_env.llm,
            SkillManager(session, client_env.skill_registry),
            prompts=RecordingPrompts(),
            feedback=feedback,
        )
        writing.generate(article_id)
        writing.revise(article_id, ["表达啰嗦"])
        targeted = writing.revise_targeted(
            article_id,
            [{"location": "第二节 结论", "description": "结论需要补充依据", "severity": "major"}],
        )
        assert outline.latest(article_id).version == 2
        assert targeted.draft.version == 3

    for name in (
        "research.md",
        "outline.md",
        "outline_revision.md",
        "writing.md",
        "writing_revision.md",
        "writing_targeted_revision.md",
    ):
        assert rendered[name]["feedback"] == feedback


def test_research_falls_back_when_search_fails(client_env):
    with _session(client_env) as session:
        article = _article(session)
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article.id, title="无搜索结果")
        service.select(article.id, topic.id)
        research = ResearchService(
            session,
            client_env.llm,
            search_tool=FakeSearchTool(error=RuntimeError("network down")),
        )
        result = research.run(article.id)
        assert result.low_confidence
        assert "network down" in result.search_error
        assert result.fact_count == 1
        assert research.list_facts(article.id)[0].status == "unverified"


def test_url_normalization_and_credibility():
    assert normalize_url("HTTPS://Example.com/a/") == "https://example.com/a"
    assert assess_credibility("https://www.gov.cn/doc")[0] == "high"
    assert assess_credibility("https://example.com/x")[0] == "low"


def test_outline_writing_review_pass(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        outline = OutlineService(session, client_env.llm).generate(article_id)
        assert outline.version == 1
        assert outline.content["sections"]

        skills = SkillManager(session, client_env.skill_registry)
        writing = WritingService(session, client_env.llm, skills)
        result = writing.generate(article_id)
        assert result.draft.version == 1
        assert result.draft.word_count > 0
        assert result.draft.citation_report[0]["status"] == "dangling"

        review = ReviewService(session, client_env.llm).review(article_id)
        assert review.verdict == "pass"
        assert review.total >= 75
        assert review.rollback_to is None

        history = OutlineService(session, client_env.llm).history(article_id)
        assert len(history) == 1


def test_review_allows_few_dangling_citations_when_valid_citations_exist(
    client_env, article_factory
):
    article_id = article_factory()
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        writing = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        writing.generate(article_id)
        draft = writing.latest(article_id)
        draft.content_md += "\n补充引用了一个不存在的来源 [9]。\n"
        session.add(
            Source(
                article_id=article_id,
                title="示例来源",
                url="https://example.com/source",
                credibility="medium",
                dedupe_key="https://example.com/source",
            )
        )
        session.commit()

        review = ReviewService(session, client_env.llm).review(article_id)
        assert review.verdict == "pass"
        assert review.rollback_to is None
        assert review.scores["fact"]["score"] == 70.0
        descriptions = [
            issue["description"]
            for issue in review.scores["fact"]["issues"]
        ]
        assert any("不存在的来源序号" in item for item in descriptions)
        assert any(
            issue["severity"] == "major" for issue in review.scores["fact"]["issues"]
        )


def test_review_blocks_clickbait_title(client_env, article_factory):
    article_id = article_factory(title="震惊！必看的 AI 内幕")
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).generate(article_id)
        session.get(Article, article_id).title = "震惊！必看的 AI 内幕"
        session.commit()

        review = ReviewService(session, client_env.llm).review(article_id)
        assert review.verdict == "fail"
        assert review.rollback_to == Stage.WRITING
        assert any(
            "标题党" in issue["description"]
            for issue in review.scores["compliance"]["issues"]
        )


def test_title_candidates_filtered_by_platform_rules():
    candidates, rejected = TitleOptimizationService._normalize_candidates(
        [
            TitleCandidate(title="正常标题：AI 工程实践", score=90),
            TitleCandidate(title="震惊！不转不是中国人", score=95),
            TitleCandidate(title="超长标题" * 30, score=99),
        ],
        ["wechat"],
    )
    assert [item.title for item in candidates] == ["正常标题：AI 工程实践"]
    assert len(rejected) == 2


def test_stage_services_inject_only_their_bound_skills(client_env, article_factory):
    article_id = article_factory()
    llm = RecordingLLM(client_env.llm)
    with _session(client_env) as session:
        manager = SkillManager(session, client_env.skill_registry)
        manager.sync()
        for stage in (Stage.TOPIC, Stage.RESEARCH, Stage.TITLE, Stage.REVIEW):
            manager.bind(stage, "writing-style-tech-review")
        manager.create_skill(
            "outline-only",
            description="只用于大纲阶段的测试技能",
            display_name="大纲专用",
            content="## 要求\n只输出三层结构。",
        )
        manager.bind(Stage.OUTLINE, "outline-only")
        try:
            TopicService(
                session, llm, hot_source=EmptyHotSource(), skills=manager
            ).recommend(article_id)
            assert "科技评论文风" in llm.systems[-1]
            assert "大纲专用" not in llm.systems[-1]

            ResearchService(
                session,
                llm,
                search_tool=FakeSearchTool(sample_results()),
                skills=manager,
            ).run(article_id)
            assert "科技评论文风" in llm.systems[-1]
            assert "大纲专用" not in llm.systems[-1]

            OutlineService(session, llm, skills=manager).generate(article_id)
            assert "大纲专用" in llm.systems[-1]
            assert "科技评论文风" not in llm.systems[-1]

            WritingService(session, llm, manager).generate(article_id)
            TitleOptimizationService(session, llm, skills=manager).optimize(article_id)
            assert "科技评论文风" in llm.systems[-1]

            ReviewService(session, llm, skills=manager).review(article_id)
            assert "科技评论文风" in llm.systems[-1]
        finally:
            manager.delete_skill("outline-only")


def test_research_deep_agent_receives_stage_skills(client_env, article_factory):
    from app.schemas.artifacts import ResearchOutput

    article_id = article_factory()

    class FakeDeepAgent:
        system_prompt: str | None = None

        def run(self, title, angle="", *, limit=8, system_prompt=None):
            self.system_prompt = system_prompt
            return ResearchOutput(sources=[], facts=[], low_confidence=True)

    fake = FakeDeepAgent()
    with _session(client_env) as session:
        manager = SkillManager(session, client_env.skill_registry)
        manager.sync()
        manager.bind(Stage.RESEARCH, "writing-style-tech-review")
        ResearchService(
            session, client_env.llm, deep_agent=fake, skills=manager
        ).run(article_id)
    assert fake.system_prompt is not None
    assert "科技评论文风" in fake.system_prompt


def test_deep_research_extracts_facts_when_agent_returns_none(client_env, article_factory):
    from app.schemas.artifacts import ExtractedSource, ResearchOutput

    article_id = article_factory()

    class FakeDeepAgent:
        def run(self, title, angle="", *, limit=8, system_prompt=None):
            return ResearchOutput(
                sources=[
                    ExtractedSource(title="官方文档", url="https://docs.python.org/3.13/")
                ],
                facts=[],
            )

    with _session(client_env) as session:
        result = ResearchService(session, client_env.llm, deep_agent=FakeDeepAgent()).run(
            article_id
        )
        assert result.source_count == 1
        assert result.fact_count == 1
        facts = session.query(Fact).filter(Fact.article_id == article_id).all()
        assert facts[0].status == "verified"


def test_deep_research_runner_uses_given_system_prompt(client_env, monkeypatch):
    from app.article_generation.research import deep_agent as module
    from app.schemas.artifacts import ResearchOutput

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create)
    monkeypatch.setattr(
        module,
        "run_with_budget",
        lambda *args, **kwargs: {
            "structured_response": ResearchOutput(sources=[], facts=[])
        },
    )
    runner = module.DeepResearchRunner(client_env.llm, FakeSearchTool([]))
    runner.run("选题", system_prompt="基础提示\n\n## 技能：研究\n只使用一手来源。")
    assert "只使用一手来源" in captured["system_prompt"]


def test_writing_prompt_includes_outline_sources_and_skill(client_env, article_factory):
    article_id = article_factory()
    captured: dict = {}

    class RecordingPrompts:
        def render(self, name, **context):
            captured["name"] = name
            captured["context"] = context
            return "writing prompt"

    with _session(client_env) as session:
        outline = OutlineService(session, client_env.llm).generate(article_id)
        ResearchService(
            session, client_env.llm, search_tool=FakeSearchTool(sample_results())
        ).run(article_id)
        service = WritingService(
            session,
            client_env.llm,
            SkillManager(session, client_env.skill_registry),
            prompts=RecordingPrompts(),
        )
        result = service.generate(article_id)

    assert captured["name"] == "writing.md"
    context = captured["context"]
    assert [section["heading"] for section in context["outline"]["sections"]] == [
        section["heading"] for section in outline.content["sections"]
    ]
    assert context["facts"]
    assert "luanhua风" in context["skills"]
    assert result.draft.content_md


def test_draft_metadata_records_tokens_model_skill_and_duration(client_env, article_factory):
    article_id = article_factory()
    factory = client_env.session_factory

    class UsageLLM:
        def structured(self, **kwargs):
            output = client_env.llm.structured(**kwargs)
            with factory() as usage_session:
                usage_session.add(
                    LLMCall(
                        article_id=kwargs.get("article_id"),
                        run_id=kwargs.get("run_id"),
                        stage=kwargs["stage"],
                        model="fake-usage-model",
                        prompt_tokens=120,
                        completion_tokens=80,
                    )
                )
                usage_session.commit()
            return output

        def get_binding(self, stage):
            return client_env.llm.get_binding(stage)

    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        service = WritingService(
            session, UsageLLM(), SkillManager(session, client_env.skill_registry)
        )
        result = service.generate(article_id)
        draft = result.draft
        assert draft.prompt_tokens == 120
        assert draft.completion_tokens == 80
        assert draft.duration_ms >= 0
        assert draft.model == "gpt-4o-mini"
        assert draft.word_count > 0
        assert isinstance(draft.skill_snapshot, list)
        assert service.history(article_id) == [draft]


def test_writing_survives_missing_skill_with_default_style(client_env, article_factory):
    from app.models.skill import Skill, SkillBinding

    article_id = article_factory()
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        skill = Skill(slug="missing-style", name="缺失风格", applies_to=[Stage.WRITING], enabled=True)
        session.add(skill)
        session.flush()
        session.add(
            SkillBinding(stage=Stage.WRITING, skill_id=skill.id, order=99, enabled=True)
        )
        session.commit()

        service = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        result = service.generate(article_id)
        assert result.draft.content_md
        assert all(item["slug"] != "missing-style" for item in result.skills_used)
        assert any(item["slug"] == "missing-style" for item in result.degraded_skills)
        assert "技能降级" in result.draft.note
        assert "技能文件缺失" in result.draft.note


def test_review_fail_routes_to_research(client_env, article_factory):
    article_id = article_factory()
    client_env.controller.review_plan = [
        {"fact": 20, "structure": 80, "readability": 80, "compliance": 80, "originality": 80, "_critical": ["fact"]},
    ]
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        WritingService(session, client_env.llm, SkillManager(session, client_env.skill_registry)).generate(
            article_id
        )
        review = ReviewService(session, client_env.llm).review(article_id)
        assert review.verdict == "fail"
        assert review.rollback_to == Stage.RESEARCH
        assert "关键问题" in review.report.rationale


def test_review_reports_dimensions_issues_and_history(client_env, article_factory):
    article_id = article_factory()
    plan = {
        "fact": 80,
        "structure": 40,
        "readability": 85,
        "compliance": 90,
        "originality": 70,
        "_critical": ["structure"],
        "_locations": {"structure": "第二节 结论"},
    }
    client_env.controller.review_plan = [plan, {**plan, "_critical": [], "structure": 90}]
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        writing = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        draft = writing.generate(article_id).draft
        service = ReviewService(session, client_env.llm)
        first = service.review(article_id)
        assert set(first.scores) == {"fact", "structure", "readability", "compliance", "originality"}
        assert first.scores["structure"]["issues"][0]["location"] == "第二节 结论"
        assert first.scores["structure"]["issues"][0]["severity"] == "critical"
        assert first.verdict == "fail"
        assert first.rollback_to == Stage.OUTLINE
        assert first.report.draft_version_id == draft.id
        assert first.report.config_version

        second = service.review(article_id)
        assert second.verdict == "pass"
        history = service.history(article_id)
        assert [report.verdict for report in history] == ["fail", "pass"]
        assert all(report.draft_version_id == draft.id for report in history)
        assert history[0].config_version == history[1].config_version


def test_review_weights_threshold_change_verdict_with_config_version(
    client_env, article_factory
):
    article_id = article_factory()
    plan = {
        "fact": 70,
        "structure": 90,
        "readability": 90,
        "compliance": 90,
        "originality": 90,
    }
    client_env.controller.review_plan = [plan, plan]
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).generate(article_id)
        strict = ReviewService(
            session, client_env.llm, weights={"fact": 1.0}, threshold=80
        ).review(article_id)
        relaxed = ReviewService(
            session, client_env.llm, weights={"fact": 1.0}, threshold=60
        ).review(article_id)
        assert strict.total == 70
        assert strict.verdict == "fail"
        assert relaxed.verdict == "pass"
        assert strict.report.config_version != relaxed.report.config_version


def test_targeted_revision_rewrites_only_flagged_sections(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        outline = OutlineService(session, client_env.llm).generate(article_id)
        assert outline.version == 1
        service = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        first = service.generate(article_id)
        untouched = "## 第一节 背景\n\n这是第一段正文，引用来源 [1]。\n\n"
        assert untouched in first.draft.content_md
        report = ReviewReport(
            article_id=article_id,
            draft_version_id=first.draft.id,
            scores={
                "structure": {
                    "score": 50,
                    "issues": [
                        {
                            "location": "## 第二节 结论",
                            "description": "结论缺少可执行建议",
                            "severity": "critical",
                        }
                    ],
                    "suggestions": [],
                }
            },
            total=60,
            verdict="fail",
            rollback_to="writing",
            rationale="结构问题",
            config_version="test",
        )
        session.add(report)
        session.commit()

        assert service.latest_review_issues(article_id)[0]["location"] == "## 第二节 结论"
        result = service.revise_targeted(article_id)
        content = result.draft.content_md
        assert result.draft.version == 2
        assert result.draft.created_by == "review_revision"
        assert "定向修订" in result.draft.note
        assert "保留未涉及章节 1 个" in result.draft.note
        assert result.draft.summary == "定向修订摘要"
        assert untouched in content
        assert "这是第二段正文，给出可执行建议。" not in content
        assert "定向修订后的结论段落。" in content
        assert content.count("## 第二节 结论") == 1


def test_targeted_revision_without_matching_location_falls_back(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        OutlineService(session, client_env.llm).generate(article_id)
        service = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        service.generate(article_id)
        report = ReviewReport(
            article_id=article_id,
            scores={
                "readability": {
                    "score": 50,
                    "issues": [{"location": "正文", "description": "太生硬", "severity": "major"}],
                    "suggestions": [],
                }
            },
            verdict="fail",
            rollback_to="writing",
        )
        session.add(report)
        session.commit()
        result = service.revise_targeted(article_id)
        assert result.draft.version == 2
        assert "审核修订" in result.draft.note


def test_targeted_revision_requires_issues(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        service = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        with pytest.raises(ValidationError):
            service.revise_targeted(article_id)
        with pytest.raises(ValidationError):
            service.revise_targeted(article_id, [])


def test_review_fail_routes_to_weakest_dimension():
    scores = {
        "fact": {"score": 90, "issues": []},
        "structure": {"score": 60, "issues": []},
        "readability": {"score": 80, "issues": []},
        "compliance": {"score": 85, "issues": []},
        "originality": {"score": 70, "issues": []},
    }
    assert determine_rollback(scores, "fail") == Stage.OUTLINE
    assert determine_rollback(scores, "pass") is None
    assert determine_rollback(
        {"structure": {"score": 90, "issues": [{"severity": "critical"}]}}, "fail"
    ) == Stage.OUTLINE
    assert determine_rollback(
        {"readability": {"score": 90, "issues": [{"severity": "CRITICAL"}]}}, "fail"
    ) == Stage.WRITING
    assert compute_total(scores) == pytest.approx(77.75, abs=0.01)


def test_outline_edit_validates(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        outline = OutlineService(session, client_env.llm).generate(article_id)
        edited = OutlineService(session, client_env.llm).edit(
            article_id,
            {
                "title": outline.content["title"],
                "hook": "新钩子",
                "sections": [{"heading": "唯一章节", "key_points": []}],
                "target_words": 900,
                "summary": "改",
                "tags": ["x"],
            },
        )
        assert edited.version == 2
        assert edited.created_by == "user"
        with pytest.raises(ValidationError):
            OutlineService(session, client_env.llm).edit(article_id, {"sections": []})


def test_user_edit_creates_version_and_citation(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        service = WritingService(session, client_env.llm, SkillManager(session, client_env.skill_registry))
        draft = service.user_edit(article_id, content_md="用户正文 [1]", summary="摘要")
        assert draft.version == 1
        assert draft.created_by == "user"
        assert draft.citation_report == [{"ref": "1", "status": "dangling"}]
        with pytest.raises(ValidationError):
            service.user_edit(article_id, content_md=" ")


class FlakyAdapter(PlatformAdapter):
    key = "flaky"
    display_name = "Flaky Platform"

    def __init__(self) -> None:
        self.calls = 0

    def validate(self, credentials):
        return AdapterAvailability(available=True, mode="api")

    def format(self, article: ArticleForFormat) -> FormatResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("flaky formatting failure")
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary,
            tags=[],
            content=article.content_md,
            format="markdown",
        )

    def publish(self, artifact, credentials):
        return PublishResult(success=True, remote_id="flaky-1")


def test_formatting_partial_failure_and_platform_retry(client_env, article_factory):
    article_id = article_factory(
        platforms=["mock", "flaky", "zhihu", "csdn"], confirmation=False
    )
    adapter = FlakyAdapter()
    client_env.registry.register(adapter)
    with _session(client_env) as session:
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).user_edit(article_id, content_md="# 正文\n\n平台失败隔离", summary="摘要")
        formatting = FormattingService(
            session,
            client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
        )
        batch = formatting.format_article(article_id)
        assert list(batch.errors) == ["flaky"]
        assert {item.platform for item in batch.outputs} == {"mock", "zhihu", "csdn"}
        assert all(item.status == "ready" for item in batch.outputs)
        failed = next(
            item for item in formatting.list_outputs(article_id) if item.platform == "flaky"
        )
        assert failed.status == "failed"
        assert "flaky formatting failure" in failed.error

        retried = formatting.retry(article_id, "flaky")
        assert retried.status == "ready"
        assert adapter.calls == 2
        assert len(formatting.list_outputs(article_id)) == 4
        assert len(
            [item for item in formatting.list_outputs(article_id) if item.platform == "flaky"]
        ) == 1


def test_formatting_and_publishing_mock(client_env, article_factory):
    article_id = article_factory(platforms=["mock", "zhihu"], confirmation=False)
    with _session(client_env) as session:
        # Create a draft without a full workflow.
        WritingService(session, client_env.llm, SkillManager(session, client_env.skill_registry)).user_edit(
            article_id, content_md="# 正文\n\n内容", summary="摘要"
        )
        credentials = CredentialService(session, CredentialCipher(client_env.settings))
        formatting = FormattingService(session, client_env.registry, credentials)
        batch = formatting.format_article(article_id)
        assert {item.platform for item in batch.outputs} == {"mock", "zhihu"}
        assert all(item.status == "ready" for item in batch.outputs)

        publishing = PublishingService(session, client_env.registry, credentials)
        summary = publishing.confirm_summary(article_id)
        assert {item["platform"] for item in summary["platforms"]} == {"mock", "zhihu"}
        assert summary["quality"]["word_count"] > 0
        assert summary["quality"]["source_count"] == 0
        assert "title_issues" in summary["quality"]

        result = publishing.publish(article_id)
        statuses = {record.platform: record.status for record in result.records}
        assert statuses["mock"] == PublishStatus.PUBLISHED
        assert statuses["zhihu"] == PublishStatus.MANUAL_REQUIRED
        assert session.get(Article, article_id).status == ArticleStatus.PUBLISHED

        second = publishing.publish(article_id)
        assert "mock" in second.skipped
        history = publishing.history(article_id, "mock")
        assert [row.status for row in history] == [
            PublishStatus.PUBLISHING,
            PublishStatus.PUBLISHED,
        ]

        backfilled = publishing.manual_backfill(
            article_id, platform="zhihu", url="https://zhuanlan.zhihu.com/p/1"
        )
        assert backfilled.status == PublishStatus.PUBLISHED
        assert backfilled.url


def test_wechat_draft_is_not_marked_published_or_uploaded_twice(client_env, article_factory):
    article_id = article_factory(platforms=["wechat"], confirmation=True)

    class DraftClient:
        calls = 0

        def create_draft(self, *, title, html, digest="", thumb_media_id=""):
            self.calls += 1
            assert thumb_media_id == "cover-1"
            return "wechat-draft-1"

        def close(self):
            pass

    draft_client = DraftClient()
    client_env.registry.get("wechat")._client_factory = lambda _credentials: draft_client
    with _session(client_env) as session:
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).user_edit(article_id, content_md="## 正文\n\n这是一篇待推入公众号草稿箱的文章。", summary="摘要")
        credentials = CredentialService(session, CredentialCipher(client_env.settings))
        credentials.set("wechat", {
            "app_id": "app-1", "app_secret": "secret-1",
            "thumb_media_id": "cover-1", "publish_mode": "draft",
        })
        FormattingService(session, client_env.registry, credentials).format_article(article_id)
        service = PublishingService(session, client_env.registry, credentials)
        first = service.publish(article_id)
        record = first.records[0]
        assert record.status == PublishStatus.DRAFT
        assert record.remote_id == "wechat-draft-1"
        assert record.published_at is None
        assert session.get(Article, article_id).status == ArticleStatus.WAITING_PUBLISH
        second = service.publish(article_id)
        assert second.skipped == ["wechat"]
        assert draft_client.calls == 1

def test_publish_without_artifact_fails_gracefully(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    with _session(client_env) as session:
        service = PublishingService(
            session,
            client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
        )
        result = service.publish(article_id)
        assert "mock" in result.errors
        record = session.query(PublishRecord).filter_by(article_id=article_id, platform="mock").one()
        assert record.status == PublishStatus.FAILED
        with pytest.raises(NotFoundError):
            service.history(article_id, "wechat")


def test_citation_report_marks_valid_and_dangling_refs(client_env, article_factory):
    article_id = article_factory()
    with _session(client_env) as session:
        ResearchService(
            session, client_env.llm, search_tool=FakeSearchTool(sample_results())
        ).run(article_id)
        OutlineService(session, client_env.llm).generate(article_id)
        service = WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        )
        generated = service.generate(article_id)
        assert generated.citation_report == [{"ref": "1", "status": "valid"}]
        edited = service.user_edit(article_id, content_md="引用 [1] 与 [9]", summary="摘要")
        assert edited.citation_report == [
            {"ref": "1", "status": "valid"},
            {"ref": "9", "status": "dangling"},
        ]
