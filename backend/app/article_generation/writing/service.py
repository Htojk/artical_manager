"""Writing stage: generate, revise and version article drafts."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.article_generation.quality import analyze_draft, count_words
from app.content_strategy import get_content_format, load_account_profile
from app.core.constants import Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import (
    Article,
    DraftVersion,
    Fact,
    OutlineVersion,
    Source,
    Topic,
)
from app.models.llm import LLMCall
from app.schemas.artifacts import DraftOutput, TargetedRevisionOutput
from app.skills.manager import SkillInjection, SkillManager, default_skill_injection

SYSTEM_PROMPT = "你是 AI 娱乐文章作者，用真实信息和具体场景写出轻松、有趣、可信的内容。"

CITATION_PATTERN = re.compile(r"\[(\d+)\]")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class DraftSection:
    heading: str
    heading_line: str
    body: str
    raw: str

    @property
    def level(self) -> int:
        return len(self.heading_line) - len(self.heading_line.lstrip("#"))


def split_sections(content_md: str) -> tuple[str, list[DraftSection]]:
    """Split Markdown into a preamble and level >= 2 sections, preserving raw text."""
    lines = content_md.splitlines(keepends=True)
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line.rstrip("\r\n"))
        if match and len(match.group(1)) >= 2:
            starts.append((index, match))
    if not starts:
        return content_md, []
    preamble = "".join(lines[: starts[0][0]])
    sections: list[DraftSection] = []
    for position, (start, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        raw = "".join(lines[start:end])
        heading_line = lines[start]
        body = "".join(lines[start + 1 : end])
        sections.append(
            DraftSection(
                heading=match.group(2).strip(),
                heading_line=heading_line,
                body=body,
                raw=raw,
            )
        )
    return preamble, sections


def _normalize_heading(text: str) -> str:
    return re.sub(r"[\s#:：\-—]+", "", text or "").lower()


@dataclass
class WritingResult:
    draft: DraftVersion
    citation_report: list[dict]
    skills_used: list[dict]
    degraded_skills: list[dict] = field(default_factory=list)


class WritingService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        skills: SkillManager,
        *,
        prompts: PromptLoader | None = None,
        feedback: str | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.skills = skills
        self.prompts = prompts or PromptLoader()
        self.feedback = (feedback or "").strip()

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

    def latest_outline(self, article_id: str) -> OutlineVersion:
        outline = self.session.scalar(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        )
        if outline is None:
            raise ValidationError("请先生成大纲")
        return outline

    def latest(self, article_id: str) -> DraftVersion | None:
        return self.session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )

    def history(self, article_id: str) -> list[DraftVersion]:
        return list(
            self.session.scalars(
                select(DraftVersion)
                .where(DraftVersion.article_id == article_id)
                .order_by(DraftVersion.version)
            )
        )

    def _next_version(self, article_id: str) -> int:
        current = self.session.scalar(
            select(func.max(DraftVersion.version)).where(DraftVersion.article_id == article_id)
        )
        return int(current or 0) + 1

    def _sources_payload(self, article_id: str) -> list[dict]:
        sources = list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        return [
            {
                "index": index,
                "title": source.title,
                "url": source.url,
                "credibility": source.credibility,
                "published_at": source.published_at,
            }
            for index, source in enumerate(sources, start=1)
        ]

    def _facts_payload(self, article_id: str) -> list[dict]:
        sources = list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        index = {source.id: position for position, source in enumerate(sources, start=1)}
        facts = list(
            self.session.scalars(
                select(Fact).where(Fact.article_id == article_id).order_by(Fact.created_at)
            )
        )
        return [
            {
                "statement": fact.statement,
                "source_index": index.get(fact.source_id, 0),
                "status": fact.status,
            }
            for fact in facts
        ]

    def _context(self, article_id: str, article: Article, topic: Topic) -> dict:
        outline = self.latest_outline(article_id)
        content_format = get_content_format(outline.content.get("content_format") or topic.content_format)
        profile = load_account_profile(self.session)
        return {
            "topic_title": topic.title,
            "topic_angle": topic.angle,
            "account_profile": profile.prompt_text(),
            "content_format": content_format.model_dump(),
            "feedback": self.feedback,
            "platforms": ", ".join(article.target_platforms or []) or "通用",
            "target_words": int(outline.content.get("target_words", 1800)),
            "outline": outline.content,
            "sources": self._sources_payload(article_id),
            "facts": self._facts_payload(article_id),
        }

    @staticmethod
    def _quality_note(note: str, content: str, sources: list, target_words: int) -> str:
        report = analyze_draft(content, sources, target_words=target_words)
        if not report["issues"]:
            return note
        return f"{note}；质量提示: {'；'.join(report['issues'][:3])}"

    def _injection(self) -> SkillInjection:
        injection = self.skills.render_for_stage(Stage.WRITING)
        if not injection.text:
            fallback = default_skill_injection()
            fallback.degraded = [*injection.degraded, *fallback.degraded]
            return fallback
        return injection

    @staticmethod
    def _degraded_note(note: str, injection: SkillInjection) -> str:
        if not injection.degraded:
            return note
        reasons = "；".join(
            f"{item.get('slug')}: {item.get('reason')}" for item in injection.degraded
        )
        return f"{note}；技能降级: {reasons}"

    def _citation_report(self, content: str, article_id: str) -> list[dict]:
        sources = list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        valid = {str(index) for index in range(1, len(sources) + 1)}
        report: list[dict] = []
        for ref in CITATION_PATTERN.findall(content):
            if ref not in valid:
                report.append({"ref": ref, "status": "dangling"})
            else:
                report.append({"ref": ref, "status": "valid"})
        return report

    def _usage_since(self, article_id: str, started_at: datetime) -> tuple[int, int]:
        row = self.session.execute(
            select(
                func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                func.coalesce(func.sum(LLMCall.completion_tokens), 0),
            ).where(
                LLMCall.article_id == article_id,
                LLMCall.stage == Stage.WRITING,
                LLMCall.created_at >= started_at,
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def generate(self, article_id: str, *, target_words: int | None = None) -> WritingResult:
        article = self._article(article_id)
        topic = self._topic(article_id, article)
        context = self._context(article_id, article, topic)
        if target_words is not None:
            context["target_words"] = target_words
        injection = self._injection()
        prompt = self.prompts.render(
            "writing.md",
            **context,
            skills=injection.text,
        )
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        output = self.llm.structured(
            stage=Stage.WRITING,
            schema=DraftOutput,
            system=SYSTEM_PROMPT,
            user=prompt,
            article_id=article_id,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens, completion_tokens = self._usage_since(article_id, started_at)
        if not output.content_md.strip():
            raise ValidationError("模型返回了空正文")
        note = self._quality_note(
            self._degraded_note("首次生成", injection),
            output.content_md,
            context["sources"],
            int(context["target_words"]),
        )
        draft = self._persist(
            article,
            output,
            created_by="model",
            note=note,
            skills_used=injection.skills,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
        report = self._citation_report(output.content_md, article_id)
        draft.citation_report = report
        self.session.commit()
        return WritingResult(
            draft=draft,
            citation_report=report,
            skills_used=injection.skills,
            degraded_skills=injection.degraded,
        )

    def revise(self, article_id: str, issues: list[str]) -> WritingResult:
        article = self._article(article_id)
        topic = self._topic(article_id, article)
        current = self.latest(article_id)
        if current is None:
            raise ValidationError("尚无可修订的正文")
        context = self._context(article_id, article, topic)
        injection = self._injection()
        prompt = self.prompts.render(
            "writing_revision.md",
            **context,
            issues=issues,
            current_draft=current.content_md,
        )
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        output = self.llm.structured(
            stage=Stage.WRITING,
            schema=DraftOutput,
            system=SYSTEM_PROMPT,
            user=prompt,
            article_id=article_id,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens, completion_tokens = self._usage_since(article_id, started_at)
        note = "审核修订: " + "；".join(issues[:3])
        note = self._quality_note(
            self._degraded_note(note, injection),
            output.content_md,
            context["sources"],
            int(context["target_words"]),
        )
        draft = self._persist(
            article,
            output,
            created_by="review_revision",
            note=note,
            skills_used=injection.skills,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
        report = self._citation_report(output.content_md, article_id)
        draft.citation_report = report
        self.session.commit()
        return WritingResult(
            draft=draft,
            citation_report=report,
            skills_used=injection.skills,
            degraded_skills=injection.degraded,
        )

    def latest_review_issues(self, article_id: str) -> list[dict]:
        from app.article_generation.review.service import latest_failed_issues

        return latest_failed_issues(self.session, article_id)

    @staticmethod
    def _matching_sections(
        sections: list[DraftSection], issues: list[dict]
    ) -> list[DraftSection]:
        if not sections:
            return []
        matched: list[DraftSection] = []
        for section in sections:
            normalized = _normalize_heading(section.heading)
            for issue in issues:
                location = _normalize_heading(issue.get("location", ""))
                if location and (location in normalized or normalized in location):
                    matched.append(section)
                    break
        return matched

    @staticmethod
    def _merge_sections(
        preamble: str,
        sections: list[DraftSection],
        output: TargetedRevisionOutput,
        targets: set[str],
    ) -> tuple[str, list[str], list[str]]:
        replacements: dict[str, str] = {}
        for item in output.sections:
            heading = _normalize_heading(item.heading)
            body = item.content_md.strip()
            heading_match = HEADING_PATTERN.match(body)
            if heading_match:
                body = body.split("\n", 1)[1].strip() if "\n" in body else ""
            replacements[heading] = body
        parts = [preamble]
        changed: list[str] = []
        untouched: list[str] = []
        for section in sections:
            key = _normalize_heading(section.heading)
            replacement = replacements.get(key)
            if key in targets and replacement is not None:
                parts.append(section.heading_line)
                if not section.heading_line.endswith("\n"):
                    parts.append("\n")
                parts.append("\n" + replacement + "\n\n")
                changed.append(section.heading)
            else:
                parts.append(section.raw)
                if key in targets:
                    changed.append(section.heading)
                else:
                    untouched.append(section.heading)
        return "".join(parts).strip() + "\n", changed, untouched

    def revise_targeted(
        self,
        article_id: str,
        issues: list[dict] | None = None,
    ) -> WritingResult:
        """Rewrite only the sections named by review issues, keep the rest verbatim."""
        article = self._article(article_id)
        current = self.latest(article_id)
        if current is None:
            raise ValidationError("尚无可修订的正文")
        resolved = issues if issues is not None else self.latest_review_issues(article_id)
        if not resolved:
            raise ValidationError("没有可用于定向修订的审核问题")

        preamble, sections = split_sections(current.content_md)
        targets = self._matching_sections(sections, resolved)
        if not targets:
            descriptions = [
                f"{item.get('location') or '正文'}：{item.get('description', '')}"
                for item in resolved
            ]
            return self.revise(article_id, descriptions)

        topic = self._topic(article_id, article)
        context = self._context(article_id, article, topic)
        injection = self._injection()
        prompt = self.prompts.render(
            "writing_targeted_revision.md",
            **context,
            issues=resolved,
            sections=[
                {"heading": section.heading, "content_md": section.body.strip()}
                for section in targets
            ],
        )
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        output = self.llm.structured(
            stage=Stage.WRITING,
            schema=TargetedRevisionOutput,
            system=SYSTEM_PROMPT,
            user=prompt,
            article_id=article_id,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens, completion_tokens = self._usage_since(article_id, started_at)
        merged, changed, untouched = self._merge_sections(
            preamble,
            sections,
            output,
            {_normalize_heading(section.heading) for section in targets},
        )
        if not changed:
            raise ValidationError("定向修订未返回任何章节")
        if not output.summary:
            output.summary = current.summary
        note = self._degraded_note(
            f"定向修订: {'、'.join(changed)}；保留未涉及章节 {len(untouched)} 个",
            injection,
        )
        note = self._quality_note(
            note,
            merged,
            context["sources"],
            int(context["target_words"]),
        )
        draft = self._persist(
            article,
            DraftOutput(
                title=article.title,
                summary=output.summary,
                content_md=merged,
                tags=output.tags,
            ),
            created_by="review_revision",
            note=note,
            skills_used=injection.skills,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
        report = self._citation_report(merged, article_id)
        draft.citation_report = report
        self.session.commit()
        return WritingResult(
            draft=draft,
            citation_report=report,
            skills_used=injection.skills,
            degraded_skills=injection.degraded,
        )

    def user_edit(
        self,
        article_id: str,
        *,
        content_md: str,
        summary: str = "",
        title: str | None = None,
    ) -> DraftVersion:
        article = self._article(article_id)
        if not content_md.strip():
            raise ValidationError("正文不能为空")
        output = DraftOutput(
            title=title or article.title,
            summary=summary,
            content_md=content_md,
            tags=[],
        )
        draft = self._persist(
            article, output, created_by="user", note="用户编辑", skills_used=[]
        )
        report = self._citation_report(content_md, article_id)
        draft.citation_report = report
        self.session.commit()
        return draft

    def _persist(
        self,
        article: Article,
        output: DraftOutput,
        *,
        created_by: str,
        note: str,
        skills_used: list[dict],
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
    ) -> DraftVersion:
        draft = DraftVersion(
            article_id=article.id,
            version=self._next_version(article.id),
            content_md=output.content_md,
            summary=output.summary,
            word_count=count_words(output.content_md),
            model=self._current_model(),
            skill_snapshot=skills_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            created_by=created_by,
            note=note,
        )
        self.session.add(draft)
        article.current_draft_version = draft.version
        if output.title:
            article.title = output.title
        self.session.commit()
        return draft

    def _current_model(self) -> str | None:
        try:
            _, profile = self.llm.get_binding(Stage.WRITING)
            return profile.model
        except Exception:  # noqa: BLE001
            return None
