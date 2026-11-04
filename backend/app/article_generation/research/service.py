"""Research stage: gather sources, dedupe, grade credibility and extract facts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.article_generation.quality import analyze_evidence
from app.article_generation.research.tools import HttpSearchTool, SearchResult
from app.core.config import get_settings
from app.core.constants import Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import Article, Fact, Source, Topic
from app.schemas.artifacts import ResearchOutput
from app.skills.manager import SkillManager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你是严谨的资料研究员，只提取可验证的事实，不虚构来源。"

HIGH_CREDIBILITY_DOMAINS = (
    ".gov",
    ".edu",
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "python.org",
    "docs.python.org",
    "developer.mozilla.org",
    "openai.com",
    "anthropic.com",
    "github.com",
)
MEDIUM_CREDIBILITY_DOMAINS = (
    "infoq.com",
    "36kr.com",
    "juejin.cn",
    "csdn.net",
    "jianshu.com",
    "woshipm.com",
    "segmentfault.com",
    "runoob.com",
    "zhihu.com",
    "medium.com",
    "sspai.com",
    "thepaper.cn",
    "jiqizhixin.com",
    "cloud.baidu.com",
)


@dataclass
class ResearchResult:
    low_confidence: bool = False
    source_count: int = 0
    fact_count: int = 0
    search_error: str | None = None
    errors: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


def source_payload(source: Source, index: int | None = None) -> dict:
    payload = {
        "title": source.title,
        "url": source.url,
        "snippet": (source.snippet or "")[:600],
        "published_at": source.published_at,
        "credibility": source.credibility,
        "credibility_reason": source.credibility_reason,
    }
    if index is not None:
        payload["index"] = index
    return payload


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def assess_credibility(url: str) -> tuple[str, str]:
    host = urlparse(url).netloc.lower()
    if any(host.endswith(domain) or domain in host for domain in HIGH_CREDIBILITY_DOMAINS):
        return "high", "政府/学术/官方文档或知名技术机构来源"
    if any(domain in host for domain in MEDIUM_CREDIBILITY_DOMAINS):
        return "medium", "行业媒体或技术社区来源"
    if not host:
        return "low", "来源域名缺失"
    return "low", "未识别的来源域名，需人工复核"


class ResearchService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        search_tool: HttpSearchTool | None = None,
        deep_agent: Any = None,
        skills: SkillManager | None = None,
        feedback: str | None = None,
        llm_timeout_seconds: float | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.search_tool = search_tool or HttpSearchTool()
        self.deep_agent = deep_agent
        self.skills = skills
        self.feedback = (feedback or "").strip()
        self.llm_timeout_seconds = (
            llm_timeout_seconds
            if llm_timeout_seconds is not None
            else get_settings().research_llm_timeout_seconds
        )

    def _system_prompt(self) -> str:
        if self.skills is None:
            return SYSTEM_PROMPT
        return self.skills.system_prompt(Stage.RESEARCH, SYSTEM_PROMPT)

    def _article(self, article_id: str) -> Article:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        return article

    def _topic(self, article_id: str, article: Article) -> Topic:
        if article.current_topic_id:
            topic = self.session.get(Topic, article.current_topic_id)
            if topic is not None:
                return topic
        topic = self.session.scalar(
            select(Topic).where(Topic.article_id == article_id, Topic.selected.is_(True))
        )
        if topic is None:
            raise ValidationError("请先选择选题")
        return topic

    def list_sources(self, article_id: str) -> list[Source]:
        return list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )

    def list_facts(self, article_id: str) -> list[Fact]:
        return list(
            self.session.scalars(
                select(Fact).where(Fact.article_id == article_id).order_by(Fact.created_at)
            )
        )

    def run(self, article_id: str, *, limit: int = 8) -> ResearchResult:
        article = self._article(article_id)
        topic = self._topic(article_id, article)
        result = ResearchResult()

        # Replace agent-generated data, keep user-added and topic-prefetched sources.
        for fact in self.list_facts(article_id):
            self.session.delete(fact)
        kept_sources: list[Source] = []
        for source in self.list_sources(article_id):
            if source.added_by in ("user", "topic"):
                kept_sources.append(source)
            else:
                self.session.delete(source)
        self.session.flush()
        existing_by_key = {
            source.dedupe_key: source for source in kept_sources if source.dedupe_key
        }

        if self.deep_agent is not None:
            try:
                kwargs: dict[str, Any] = {"limit": limit}
                if self.feedback:
                    kwargs["feedback"] = self.feedback
                if self.skills is not None:
                    kwargs["system_prompt"] = self._system_prompt()
                output = self.deep_agent.run(topic.title, topic.angle, **kwargs)
            except Exception as exc:  # noqa: BLE001 - fall back to plain search
                result.errors.append(f"deep agent 研究失败，回退普通搜索: {exc}")
                logger.warning("deep research failed for %s: %s", article_id, exc)
            else:
                created, index_map = self._persist_deep_sources(
                    article_id, output, existing_by_key=existing_by_key
                )
                if created and not output.facts:
                    # The agent found sources but skipped extraction; run the
                    # deterministic extraction prompt instead of losing evidence.
                    extracted = self._extract_facts(article_id, topic, created)
                    if extracted is not None:
                        output = output.model_copy(
                            update={
                                "facts": extracted.facts,
                                "low_confidence": (
                                    output.low_confidence or extracted.low_confidence
                                ),
                            }
                        )
                self._persist_facts(
                    article_id,
                    created,
                    output,
                    force_unverified=not created,
                    index_map=index_map,
                )
                self.session.commit()
                result.evidence = analyze_evidence(
                    self.list_sources(article_id), self.list_facts(article_id)
                )
                result.low_confidence = bool(
                    output.low_confidence
                    or not created
                    or result.evidence["low_confidence"]
                )
                if output.notes:
                    result.errors.append(output.notes)
                result.source_count = len(self.list_sources(article_id))
                result.fact_count = len(self.list_facts(article_id))
                return result

        query = f"{topic.title} {topic.angle}".strip()
        search_results: list[SearchResult] = []
        try:
            search_results = self.search_tool.search(query, limit=limit)
        except Exception as exc:  # noqa: BLE001 - degrade to model knowledge
            result.search_error = str(exc)
            logger.warning("research search failed for %s: %s", article_id, exc)

        all_sources: list[Source] = list(kept_sources)
        seen: set[str] = set(existing_by_key)
        for item in search_results:
            key = normalize_url(item.url)
            if key in seen:
                continue
            seen.add(key)
            credibility, reason = assess_credibility(item.url)
            source = Source(
                article_id=article_id,
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                published_at=item.published_at,
                credibility=credibility,
                credibility_reason=reason,
                dedupe_key=key,
                added_by="agent",
            )
            self.session.add(source)
            all_sources.append(source)
        self.session.flush()

        if all_sources:
            prompt = self.prompts.render(
                "research.md",
                topic_title=topic.title,
                topic_angle=topic.angle,
                feedback=self.feedback,
                sources=[
                    source_payload(source) for source in all_sources
                ],
            )
            try:
                output = self.llm.structured(
                    stage=Stage.RESEARCH,
                    schema=ResearchOutput,
                    system=self._system_prompt(),
                    user=prompt,
                    article_id=article_id,
                    timeout_seconds=self.llm_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - keep the sources we found
                logger.warning("fact extraction failed for %s: %s", article_id, exc)
                result.errors.append(f"事实提取失败，已保留来源: {exc}")
                result.low_confidence = True
            else:
                self._persist_facts(article_id, all_sources, output)
                result.low_confidence = bool(output.low_confidence)
                if output.notes:
                    result.errors.append(output.notes)
        else:
            prompt = self.prompts.render(
                "research_fallback.md",
                topic_title=topic.title,
                topic_angle=topic.angle,
                feedback=self.feedback,
            )
            try:
                output = self.llm.structured(
                    stage=Stage.RESEARCH,
                    schema=ResearchOutput,
                    system=self._system_prompt(),
                    user=prompt,
                    article_id=article_id,
                    timeout_seconds=self.llm_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - degrade to an empty evidence set
                logger.warning("fallback fact extraction failed for %s: %s", article_id, exc)
                result.errors.append(f"事实提取失败: {exc}")
            else:
                self._persist_facts(article_id, [], output, force_unverified=True)
            result.low_confidence = True

        self.session.commit()
        result.evidence = analyze_evidence(
            self.list_sources(article_id), self.list_facts(article_id)
        )
        result.low_confidence = bool(
            result.low_confidence or result.evidence["low_confidence"]
        )
        result.source_count = len(self.list_sources(article_id))
        result.fact_count = len(self.list_facts(article_id))
        return result

    def _extract_facts(
        self,
        article_id: str,
        topic: Topic,
        sources: list[Source],
    ) -> ResearchOutput | None:
        if not sources:
            return None
        prompt = self.prompts.render(
            "research.md",
            topic_title=topic.title,
            topic_angle=topic.angle,
            feedback=self.feedback,
            sources=[source_payload(source) for source in sources],
        )
        try:
            return self.llm.structured(
                stage=Stage.RESEARCH,
                schema=ResearchOutput,
                system=self._system_prompt(),
                user=prompt,
                article_id=article_id,
                timeout_seconds=self.llm_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - keep the sources we already have
            logger.warning("fact extraction failed for %s: %s", article_id, exc)
            return None

    def _persist_deep_sources(
        self,
        article_id: str,
        output: ResearchOutput,
        *,
        existing_by_key: dict[str, Source] | None = None,
    ) -> tuple[list[Source], dict[int, int]]:
        existing_by_key = existing_by_key if existing_by_key is not None else {}
        sources: list[Source] = []
        seen: dict[str, int] = {}
        index_map: dict[int, int] = {}
        for position, item in enumerate(output.sources, start=1):
            key = normalize_url(item.url)
            if key in seen:
                index_map[position] = seen[key]
                continue
            source = existing_by_key.get(key)
            if source is None:
                credibility, reason = assess_credibility(item.url)
                source = Source(
                    article_id=article_id,
                    title=item.title or item.url,
                    url=item.url,
                    snippet=item.snippet,
                    published_at=item.published_at,
                    credibility=credibility,
                    credibility_reason=reason,
                    dedupe_key=key,
                    added_by="agent",
                )
                self.session.add(source)
                self.session.flush()
                existing_by_key[key] = source
            sources.append(source)
            seen[key] = len(sources)
            index_map[position] = len(sources)
        return sources, index_map

    def _persist_facts(
        self,
        article_id: str,
        sources: list[Source],
        output: ResearchOutput,
        *,
        force_unverified: bool = False,
        index_map: dict[int, int] | None = None,
    ) -> None:
        seen: set[str] = set()
        for fact in output.facts:
            statement = fact.statement.strip()
            if len(statement) < 6 or statement in seen:
                continue
            seen.add(statement)
            source: Source | None = None
            target = index_map.get(fact.source_index, fact.source_index) if index_map else fact.source_index
            if not force_unverified and 1 <= target <= len(sources):
                source = sources[target - 1]
            status = "verified" if source is not None else "unverified"
            self.session.add(
                Fact(
                    article_id=article_id,
                    source_id=source.id if source else None,
                    statement=statement,
                    status=status,
                )
            )

    def add_source(
        self,
        article_id: str,
        *,
        title: str,
        url: str,
        snippet: str = "",
    ) -> Source:
        self._article(article_id)
        if not url.strip():
            raise ValidationError("来源链接不能为空")
        key = normalize_url(url)
        existing = self.session.scalar(
            select(Source).where(Source.article_id == article_id, Source.dedupe_key == key)
        )
        if existing is not None:
            return existing
        credibility, reason = assess_credibility(url)
        source = Source(
            article_id=article_id,
            title=title.strip() or url,
            url=url.strip(),
            snippet=snippet.strip(),
            credibility=credibility,
            credibility_reason=reason,
            dedupe_key=key,
            added_by="user",
        )
        self.session.add(source)
        self.session.commit()
        return source

    def remove_source(self, article_id: str, source_id: str) -> None:
        source = self.session.get(Source, source_id)
        if source is None or source.article_id != article_id:
            raise NotFoundError("来源不存在")
        for fact in self.list_facts(article_id):
            if fact.source_id == source_id:
                fact.source_id = None
                fact.status = "unverified"
        self.session.delete(source)
        self.session.commit()
