"""Outline generation, revision and user editing."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import Stage
from app.content_strategy import get_content_format, load_account_profile
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import Article, Fact, OutlineVersion, Source, Topic
from app.schemas.artifacts import OutlineOutput
from app.skills.manager import SkillManager

SYSTEM_PROMPT = "你是 AI 娱乐文章结构编辑，擅长用真实场景、清楚的信息和自然反差组织内容。"


class OutlineService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        skills: SkillManager | None = None,
        feedback: str | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.skills = skills
        self.feedback = (feedback or "").strip()

    def _system_prompt(self) -> str:
        if self.skills is None:
            return SYSTEM_PROMPT
        return self.skills.system_prompt(Stage.OUTLINE, SYSTEM_PROMPT)

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

    def latest(self, article_id: str) -> OutlineVersion | None:
        return self.session.scalar(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        )

    def history(self, article_id: str) -> list[OutlineVersion]:
        return list(
            self.session.scalars(
                select(OutlineVersion)
                .where(OutlineVersion.article_id == article_id)
                .order_by(OutlineVersion.version)
            )
        )

    def _next_version(self, article_id: str) -> int:
        current = self.session.scalar(
            select(func.max(OutlineVersion.version)).where(OutlineVersion.article_id == article_id)
        )
        return int(current or 0) + 1

    def _context(self, article_id: str, article: Article, topic: Topic) -> dict:
        content_format = get_content_format(topic.content_format)
        profile = load_account_profile(self.session)
        sources = list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        source_index = {source.id: index for index, source in enumerate(sources, start=1)}
        facts = list(
            self.session.scalars(
                select(Fact).where(Fact.article_id == article_id).order_by(Fact.created_at)
            )
        )
        return {
            "topic_title": topic.title,
            "topic_angle": topic.angle,
            "account_profile": profile.prompt_text(),
            "content_format": content_format.model_dump(),
            "feedback": self.feedback,
            "platforms": ", ".join(article.target_platforms or []) or "通用",
            "sources": [
                {
                    "index": index,
                    "title": source.title,
                    "url": source.url,
                    "credibility": source.credibility,
                }
                for index, source in enumerate(sources, start=1)
            ],
            "facts": [
                {
                    "statement": fact.statement,
                    "source_index": source_index.get(fact.source_id, 0),
                    "status": fact.status,
                }
                for fact in facts
            ],
            "_source_count": len(sources),
        }

    @staticmethod
    def _sanitize(
        output: OutlineOutput, fallback_title: str, source_count: int
    ) -> OutlineOutput:
        sections = []
        seen: set[str] = set()
        for section in output.sections:
            heading = section.heading.strip()
            key = heading.lower()
            if not heading or key in seen:
                continue
            seen.add(key)
            refs = sorted({ref for ref in section.source_refs if 1 <= ref <= source_count})
            sections.append(
                section.model_copy(
                    update={
                        "heading": heading,
                        "key_points": [point.strip() for point in section.key_points if point.strip()],
                        "source_refs": refs,
                    }
                )
            )
        if not sections:
            raise ValidationError("大纲至少需要包含一个有效章节")
        words = max(400, min(int(output.target_words or 1800), 6000))
        return output.model_copy(
            update={
                "title": output.title.strip() or fallback_title,
                "hook": output.hook.strip(),
                "sections": sections,
                "target_words": words,
            }
        )

    def generate(
        self,
        article_id: str,
        *,
        target_words: int | None = None,
    ) -> OutlineVersion:
        article = self._article(article_id)
        topic = self._topic(article_id, article)
        context = self._context(article_id, article, topic)
        effective_target = target_words or context["content_format"]["target_words"]
        prompt = self.prompts.render(
            "outline.md",
            **context,
            target_words=effective_target,
        )
        output = self.llm.structured(
            stage=Stage.OUTLINE,
            schema=OutlineOutput,
            system=self._system_prompt(),
            user=prompt,
            article_id=article_id,
        )
        output = self._sanitize(output, topic.title, context["_source_count"])
        output.content_format = context["content_format"]["key"]
        output.target_words = max(400, min(int(effective_target), 6000))
        return self._persist(article, output.model_dump(), created_by="model", note="首次生成")

    def revise(self, article_id: str, issues: list[str]) -> OutlineVersion:
        article = self._article(article_id)
        topic = self._topic(article_id, article)
        current = self.latest(article_id)
        if current is None:
            raise ValidationError("尚无可修订的大纲")
        context = self._context(article_id, article, topic)
        prompt = self.prompts.render(
            "outline_revision.md",
            **context,
            issues=issues,
            current_outline=current.content,
            target_words=current.content.get("target_words", 1800),
        )
        output = self.llm.structured(
            stage=Stage.OUTLINE,
            schema=OutlineOutput,
            system=self._system_prompt(),
            user=prompt,
            article_id=article_id,
        )
        output = self._sanitize(output, topic.title, context["_source_count"])
        output.content_format = context["content_format"]["key"]
        note = "审核修订: " + "；".join(issues[:3])
        return self._persist(article, output.model_dump(), created_by="review_revision", note=note)

    def edit(self, article_id: str, content: dict, *, note: str = "用户编辑") -> OutlineVersion:
        article = self._article(article_id)
        try:
            output = OutlineOutput.model_validate(content)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"大纲内容无效: {exc}") from exc
        if not output.sections:
            raise ValidationError("大纲至少需要包含一个章节")
        return self._persist(article, output.model_dump(), created_by="user", note=note)

    def _persist(
        self, article: Article, content: dict, *, created_by: str, note: str
    ) -> OutlineVersion:
        version = OutlineVersion(
            article_id=article.id,
            version=self._next_version(article.id),
            content=content,
            created_by=created_by,
            note=note,
        )
        self.session.add(version)
        article.current_outline_version = version.version
        self.session.commit()
        return version
