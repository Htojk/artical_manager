"""Manual and AI-assisted topic selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.article_generation.research.service import assess_credibility, normalize_url
from app.article_generation.topic_selection.articles import ArticleContentFetcher
from app.article_generation.topic_selection.hot_topics import HotSignal, HotTopicSource
from app.content_strategy import CONTENT_FORMATS, entertainment_score, load_account_profile
from app.core.config import get_settings
from app.core.constants import ArticleStatus, Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import Article, Source, Topic
from app.schemas.artifacts import TopicCandidates
from app.skills.manager import SkillManager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你是 AI 娱乐账号的内容策划，擅长把真实 AI 新闻和使用场景变成有趣、可核查的选题。"
MIN_ENTERTAINMENT_SCORE = 60.0
MAX_CANDIDATE_ROUNDS = 3


def _signal_payload(signal: HotSignal) -> dict:
    return {
        "index": signal.index,
        "title": signal.title,
        "source": signal.source,
        "url": signal.url,
        "published_at": signal.published_at,
        "heat": signal.heat,
    }


@dataclass
class RecommendationResult:
    topics: list[Topic] = field(default_factory=list)
    fallback_used: bool = False
    hot_signal_count: int = 0
    hot_errors: list[str] = field(default_factory=list)


@dataclass
class SourceFetchResult:
    ok: bool = False
    source_id: str | None = None
    title: str = ""
    error: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "source_id": self.source_id,
            "title": self.title,
            "error": self.error,
            "reason": self.reason,
        }


@dataclass
class SelectionResult:
    topic: Topic
    source_fetch: SourceFetchResult


class TopicService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        hot_source: HotTopicSource | None = None,
        content_fetcher: ArticleContentFetcher | None = None,
        skills: SkillManager | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.skills = skills
        settings = get_settings()
        self.hot_source = hot_source or HotTopicSource(specs=settings.hot_source_specs)
        self.content_fetcher = content_fetcher or ArticleContentFetcher()

    def _article(self, article_id: str) -> Article:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        return article

    def list_topics(self, article_id: str) -> list[Topic]:
        return list(
            self.session.scalars(
                select(Topic).where(Topic.article_id == article_id).order_by(Topic.created_at)
            )
        )

    def create_manual(
        self,
        article_id: str,
        *,
        title: str,
        angle: str = "",
        target_platforms: list[str] | None = None,
        rationale: str = "用户手动输入",
        content_format: str = "hot_take",
    ) -> Topic:
        if not title or not title.strip():
            raise ValidationError("选题标题不能为空")
        if content_format not in CONTENT_FORMATS:
            raise ValidationError("不支持的内容形式")
        article = self._article(article_id)
        topic = Topic(
            article_id=article_id,
            source="manual",
            title=title.strip(),
            angle=angle.strip() or title.strip(),
            rationale=rationale,
            target_platforms=target_platforms or list(article.target_platforms or []),
            hot_signals=[],
            content_format=content_format,
            selected=False,
        )
        self.session.add(topic)
        if not article.title:
            article.title = topic.title
        article.topic_mode = "manual"
        article.status = ArticleStatus.DRAFT
        self.session.commit()
        return topic

    def recommend(
        self,
        article_id: str,
        *,
        domain: str = "",
        count: int = 5,
        exclude_titles: list[str] | None = None,
    ) -> RecommendationResult:
        if count != 5:
            raise ValidationError("AI 推荐固定生成 5 个候选选题")
        article = self._article(article_id)
        profile = load_account_profile(self.session)
        platforms = list(article.target_platforms or [])
        exclude = [title for title in (exclude_titles or []) if title]

        signals: list[HotSignal] = []
        hot_errors: list[str] = []
        try:
            signals = self.hot_source.fetch()
            hot_errors = list(self.hot_source.errors)
        except Exception as exc:  # noqa: BLE001 - degrade to model knowledge
            hot_errors = [str(exc)]

        candidates = self._generate_candidates(
            domain=domain or article.title or profile.default_domain,
            profile=profile,
            platforms=platforms,
            signals=signals,
            exclude=exclude,
        )
        topics: list[Topic] = []
        for candidate in candidates:
            scores = candidate.entertainment_scores
            score = entertainment_score(scores) if scores else candidate.discussion_score
            content_format = candidate.content_format
            if content_format not in profile.preferred_formats or content_format not in CONTENT_FORMATS:
                content_format = profile.preferred_formats[0]
            linked: list[dict] = []
            if 1 <= candidate.hot_signal_index <= len(signals):
                linked = [_signal_payload(signals[candidate.hot_signal_index - 1])]
            topic = Topic(
                article_id=article_id,
                source="ai_hot" if linked else "ai",
                title=candidate.title.strip(),
                angle=candidate.angle.strip(),
                rationale=candidate.rationale.strip(),
                target_platforms=candidate.target_platforms or platforms,
                hot_signals=linked,
                discussion_score=candidate.discussion_score,
                discussion_reason=candidate.discussion_reason.strip(),
                entertainment_score=score,
                entertainment_reason=candidate.entertainment_reason.strip() or candidate.discussion_reason.strip(),
                entertainment_scores=scores,
                content_format=content_format,
                selected=False,
            )
            self.session.add(topic)
            topics.append(topic)
        article.topic_mode = "ai"
        article.status = ArticleStatus.DRAFT
        self.session.commit()
        return RecommendationResult(
            topics=topics,
            fallback_used=not signals,
            hot_signal_count=len(signals),
            hot_errors=hot_errors,
        )

    def _generate_candidates(
        self,
        *,
        domain: str,
        profile,
        platforms: list[str],
        signals: list[HotSignal],
        exclude: list[str],
    ) -> list:
        seen = {title.strip().lower() for title in exclude}
        unique = []
        for _round in range(MAX_CANDIDATE_ROUNDS):
            prompt = self.prompts.render(
                "topic_selection.md",
                count=5,
                domain=domain,
                account_profile=profile.prompt_text(),
                preferred_formats=[CONTENT_FORMATS[key] for key in profile.preferred_formats],
                platforms=", ".join(platforms) or "通用",
                hot_signals=[signal.prompt_payload() for signal in signals],
                exclude_titles=exclude + [item.title for item in unique],
            )
            system = (
                self.skills.system_prompt(Stage.TOPIC, SYSTEM_PROMPT)
                if self.skills is not None
                else SYSTEM_PROMPT
            )
            output = self.llm.structured(
                stage=Stage.TOPIC,
                schema=TopicCandidates,
                system=system,
                user=prompt,
            )
            for candidate in output.candidates:
                key = candidate.title.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                score = (
                    entertainment_score(candidate.entertainment_scores)
                    if candidate.entertainment_scores
                    else candidate.discussion_score
                )
                if score < MIN_ENTERTAINMENT_SCORE:
                    continue
                unique.append(candidate)
                if len(unique) == 5:
                    break
            if len(unique) == 5:
                break
        if len(unique) < 5:
            raise ValidationError("模型未能生成足够适合账号的候选选题，请重试")
        return unique[:5]

    def select(self, article_id: str, topic_id: str) -> SelectionResult:
        article = self._article(article_id)
        topic = self.session.get(Topic, topic_id)
        if topic is None or topic.article_id != article_id:
            raise NotFoundError("选题不存在")
        for item in self.list_topics(article_id):
            item.selected = item.id == topic_id
        article.current_topic_id = topic.id
        article.title = topic.title
        article.status = ArticleStatus.DRAFT
        self.session.commit()
        return SelectionResult(
            topic=topic, source_fetch=self._fetch_topic_article(article_id, topic)
        )

    def _linked_signal(self, topic: Topic) -> dict:
        for item in topic.hot_signals or []:
            if isinstance(item, dict) and str(item.get("url") or "").strip():
                return item
        return {}

    def _content_selector(self, url: str) -> str:
        host = urlparse(url).netloc.lower()
        for spec in get_settings().hot_source_specs:
            if spec.content_selector and urlparse(spec.url).netloc.lower() == host:
                return spec.content_selector
        return ""

    def _fetch_topic_article(self, article_id: str, topic: Topic) -> SourceFetchResult:
        signal = self._linked_signal(topic)
        if not signal:
            return SourceFetchResult(reason="候选未关联文章链接")
        url = str(signal.get("url") or "").strip()
        title = str(signal.get("title") or topic.title).strip()
        key = normalize_url(url)
        existing = self.session.scalar(
            select(Source).where(Source.article_id == article_id, Source.dedupe_key == key)
        )
        if existing is not None:
            return SourceFetchResult(
                ok=True,
                source_id=existing.id,
                title=existing.title,
                reason="链接已作为来源存在，已复用",
            )
        try:
            text = self.content_fetcher.fetch(
                url, content_selector=self._content_selector(url)
            )
        except Exception as exc:  # noqa: BLE001 - selection must not be blocked
            logger.warning("topic article fetch failed %s: %s", url, exc)
            return SourceFetchResult(title=title, error=str(exc))
        if not text.strip():
            return SourceFetchResult(title=title, error="未提取到正文内容")

        credibility, credibility_reason = assess_credibility(url)
        source = Source(
            article_id=article_id,
            title=title or url,
            url=url,
            snippet=text,
            published_at=signal.get("published_at"),
            credibility=credibility,
            credibility_reason=credibility_reason,
            dedupe_key=key,
            added_by="topic",
        )
        self.session.add(source)
        self.session.commit()
        return SourceFetchResult(
            ok=True,
            source_id=source.id,
            title=source.title,
            reason="已抓取正文并保存为来源",
        )

    def selected_topic(self, article_id: str) -> Topic:
        article = self._article(article_id)
        if article.current_topic_id:
            topic = self.session.get(Topic, article.current_topic_id)
            if topic is not None:
                return topic
        topic = self.session.scalar(
            select(Topic).where(Topic.article_id == article_id, Topic.selected.is_(True))
        )
        if topic is None:
            raise ValidationError("请先选择一个选题")
        return topic

    def update_topic(self, article_id: str, topic_id: str, **fields: str) -> Topic:
        topic = self.session.get(Topic, topic_id)
        if topic is None or topic.article_id != article_id:
            raise NotFoundError("选题不存在")
        for key in ("title", "angle", "rationale"):
            if key in fields and fields[key]:
                setattr(topic, key, fields[key].strip())
        if fields.get("content_format"):
            if fields["content_format"] not in CONTENT_FORMATS:
                raise ValidationError("不支持的内容形式")
            topic.content_format = fields["content_format"]
        article = self._article(article_id)
        if article.current_topic_id == topic_id:
            article.title = topic.title
        self.session.commit()
        return topic
