"""Account profile, entertainment selection and format handoff."""

from __future__ import annotations

from app.article_generation.outline.service import OutlineService
from app.article_generation.review.service import ReviewService
from app.article_generation.title_optimization.service import TitleOptimizationService
from app.article_generation.topic_selection.service import TopicService
from app.article_generation.writing.service import WritingService
from app.content_strategy import AccountProfile, entertainment_score, load_account_profile
from app.models.article import Article
from app.schemas.artifacts import TopicCandidate, TopicCandidates
from app.skills.manager import SkillManager


def test_account_profile_is_editable_and_used_by_topic_prompt(client_env):
    profile = AccountProfile(
        name="AI 乒乓游戏室",
        audience="爱玩游戏和乒乓的 AI 新手",
        content_pillars=["AI × 乒乓", "AI × 游戏"],
        preferred_formats=["creative_experiment", "hot_take"],
    )
    response = client_env.client.put("/api/settings/account_profile", json={"value": profile.model_dump()})
    assert response.status_code == 200
    assert response.json()["value"]["name"] == "AI 乒乓游戏室"

    class NoHot:
        errors: list[str] = []

        def fetch(self):
            return []

    class CaptureLLM:
        user = ""

        def structured(self, **kwargs):
            self.user = kwargs["user"]
            return client_env.llm.structured(**kwargs)

    recorder = CaptureLLM()
    with client_env.session_factory() as session:
        assert load_account_profile(session).audience == profile.audience
        article = Article(target_platforms=["mock"])
        session.add(article)
        session.commit()
        TopicService(session, recorder, hot_source=NoHot()).recommend(article.id)
    assert "AI 乒乓游戏室" in recorder.user
    assert "AI × 乒乓" in recorder.user
    assert "creative_experiment" in recorder.user
    assert "tool_test" not in recorder.user


def test_entertainment_score_and_format_flow_to_outline_and_writing(client_env):
    scores = {
        "account_fit": 90,
        "novelty": 80,
        "relatability": 70,
        "demonstrability": 80,
        "humor_potential": 90,
    }

    class NoHot:
        errors: list[str] = []

        def fetch(self):
            return []

    class CaptureLLM:
        users: list[str] = []

        def structured(self, **kwargs):
            self.users.append(kwargs["user"])
            if kwargs["schema"] is TopicCandidates:
                return TopicCandidates(candidates=[
                    TopicCandidate(
                        title=f"AI 脑洞候选第{i}篇",
                        angle="模拟 AI 游戏 NPC 与玩家的对话",
                        rationale="游戏玩家熟悉这个场景",
                        content_format="creative_experiment",
                        entertainment_scores=scores,
                        entertainment_reason="场景熟悉，且有自然反差",
                    )
                    for i in range(5)
                ])
            return client_env.llm.structured(**kwargs)

    recorder = CaptureLLM()
    with client_env.session_factory() as session:
        article = Article(target_platforms=["mock"])
        session.add(article)
        session.commit()
        service = TopicService(session, recorder, hot_source=NoHot())
        result = service.recommend(article.id)
        topic = result.topics[0]
        assert topic.entertainment_score == entertainment_score(scores)
        assert topic.content_format == "creative_experiment"
        assert topic.source == "ai"
        service.select(article.id, topic.id)
        outline = OutlineService(session, recorder).generate(article.id)
        assert outline.content["content_format"] == "creative_experiment"
        assert outline.content["target_words"] == 800
        assert "目标字数：800" in recorder.users[-1]
        WritingService(session, recorder, SkillManager(session, client_env.skill_registry)).generate(article.id)
        assert "AI 脑洞实验" in recorder.users[-1]
        assert "虚构桥段" in recorder.users[-1]
        assert "目标字数：约 800 字" in recorder.users[-1]
        TitleOptimizationService(session, recorder).optimize(article.id)
        assert "AI 娱乐观察" in recorder.users[-1]
        ReviewService(session, recorder).review(article.id)
        assert "AI 娱乐观察" in recorder.users[-1]
