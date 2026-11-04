"""Generate, score and version article title candidates after writing."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.article_generation.quality import validate_title
from app.content_strategy import load_account_profile
from app.core.constants import Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import Article, DraftVersion, OutlineVersion, TitleVersion, Topic
from app.models.llm import LLMCall
from app.schemas.artifacts import TitleCandidate, TitleOptimizationOutput
from app.skills.manager import SkillManager

SYSTEM_PROMPT = "你是资深内容编辑，擅长在忠于正文事实的前提下设计有吸引力的标题。"

HEADING_PATTERN = re.compile(r"^#{2,6}\s+(.+?)\s*$", re.MULTILINE)
MAX_EXCERPT_CHARS = 1800
MIN_TITLE_CHARS = 2
MAX_TITLE_CHARS = 120


@dataclass
class TitleResult:
    title_version: TitleVersion
    candidates: list[TitleCandidate]


class TitleOptimizationService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        skills: SkillManager | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.skills = skills

    def _system_prompt(self) -> str:
        if self.skills is None:
            return SYSTEM_PROMPT
        return self.skills.system_prompt(Stage.TITLE, SYSTEM_PROMPT)

    def _article(self, article_id: str) -> Article:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        return article

    def latest_draft(self, article_id: str) -> DraftVersion:
        draft = self.session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )
        if draft is None:
            raise ValidationError("尚无正文可进行标题优化")
        return draft

    def latest(self, article_id: str) -> TitleVersion | None:
        return self.session.scalar(
            select(TitleVersion)
            .where(TitleVersion.article_id == article_id)
            .order_by(TitleVersion.version.desc())
        )

    def history(self, article_id: str) -> list[TitleVersion]:
        return list(
            self.session.scalars(
                select(TitleVersion)
                .where(TitleVersion.article_id == article_id)
                .order_by(TitleVersion.version)
            )
        )

    def optimize(self, article_id: str) -> TitleResult:
        article = self._article(article_id)
        draft = self.latest_draft(article_id)
        topic = (
            self.session.get(Topic, article.current_topic_id)
            if article.current_topic_id
            else None
        )
        headings = self._headings(article_id, draft)
        prompt = self.prompts.render(
            "title_optimization.md",
            account_profile=load_account_profile(self.session).prompt_text(),
            topic_title=topic.title if topic else article.title,
            current_title=article.title or draft.summary[:40],
            platforms=", ".join(article.target_platforms or []) or "通用",
            summary=draft.summary,
            headings=headings,
            content_excerpt=draft.content_md[:MAX_EXCERPT_CHARS],
            history_titles=self._history_titles(article_id),
        )
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        output = self.llm.structured(
            stage=Stage.TITLE,
            schema=TitleOptimizationOutput,
            system=self._system_prompt(),
            user=prompt,
            article_id=article_id,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens, completion_tokens = self._usage_since(article_id, started_at)
        platforms = list(article.target_platforms or [])
        candidates, rejected = self._normalize_candidates(output.candidates, platforms)
        selected = self._resolve_selected(output.recommended, candidates, platforms)
        note = "模型优化"
        if rejected:
            note += "；过滤不合规候选 " + "、".join(rejected[:3])
        version = self._persist(
            article,
            candidates,
            selected_title=selected,
            strategy=output.strategy,
            created_by="model",
            note=note,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
        return TitleResult(title_version=version, candidates=candidates)

    def select(self, article_id: str, title: str, *, note: str = "用户选择") -> TitleVersion:
        article = self._article(article_id)
        cleaned = title.strip()
        if not (MIN_TITLE_CHARS <= len(cleaned) <= MAX_TITLE_CHARS):
            raise ValidationError(f"标题长度需在 {MIN_TITLE_CHARS}-{MAX_TITLE_CHARS} 字之间")
        issues = validate_title(cleaned, list(article.target_platforms or []))
        if issues:
            raise ValidationError("；".join(issues))
        latest = self.latest(article_id)
        candidates = list(latest.candidates or []) if latest is not None else []
        return self._persist(
            article,
            [TitleCandidate(**item) for item in candidates if isinstance(item, dict)],
            selected_title=cleaned,
            strategy=latest.strategy if latest is not None else "",
            created_by="user",
            note=note,
        )

    @staticmethod
    def _normalize_candidates(
        items: list[TitleCandidate], platforms: list[str] | None = None
    ) -> tuple[list[TitleCandidate], list[str]]:
        seen: set[str] = set()
        normalized: list[TitleCandidate] = []
        rejected: list[str] = []
        for item in items:
            title = item.title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            issues = validate_title(title, platforms or [])
            if issues:
                rejected.append(f"{title}（{issues[0]}）")
                continue
            normalized.append(item.model_copy(update={"title": title}))
        if not normalized:
            # Never fail the stage on taste: keep candidates and surface warnings.
            normalized = [
                item.model_copy(update={"title": item.title.strip()})
                for item in items
                if item.title.strip()
            ]
            rejected = []
        if not normalized:
            raise ValidationError("模型未返回可用的标题候选")
        normalized.sort(key=lambda item: item.score, reverse=True)
        return normalized, rejected

    @staticmethod
    def _resolve_selected(
        recommended: str, candidates: list[TitleCandidate], platforms: list[str] | None = None
    ) -> str:
        cleaned = (recommended or "").strip()
        titles = {item.title for item in candidates}
        if cleaned in titles and not validate_title(cleaned, platforms or []):
            return cleaned
        return candidates[0].title

    def _headings(self, article_id: str, draft: DraftVersion) -> list[str]:
        outline = self.session.scalar(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        )
        if outline is not None:
            sections = outline.content.get("sections", [])
            headings = [str(item.get("heading", "")).strip() for item in sections]
            if any(headings):
                return [heading for heading in headings if heading]
        return HEADING_PATTERN.findall(draft.content_md)

    def _history_titles(self, article_id: str) -> list[str]:
        titles: list[str] = []
        for version in self.history(article_id):
            if version.selected_title:
                titles.append(version.selected_title)
        return list(dict.fromkeys(titles))[-10:]

    def _usage_since(self, article_id: str, started_at: datetime) -> tuple[int, int]:
        row = self.session.execute(
            select(
                func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
                func.coalesce(func.sum(LLMCall.completion_tokens), 0),
            ).where(
                LLMCall.article_id == article_id,
                LLMCall.stage == Stage.TITLE,
                LLMCall.created_at >= started_at,
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def _persist(
        self,
        article: Article,
        candidates: list[TitleCandidate],
        *,
        selected_title: str,
        strategy: str,
        created_by: str,
        note: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
    ) -> TitleVersion:
        current = self.session.scalar(
            select(func.max(TitleVersion.version)).where(
                TitleVersion.article_id == article.id
            )
        )
        version = TitleVersion(
            article_id=article.id,
            version=int(current or 0) + 1,
            candidates=[item.model_dump() for item in candidates],
            selected_title=selected_title,
            strategy=strategy,
            model=self._current_model(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            created_by=created_by,
            note=note,
        )
        self.session.add(version)
        article.title = selected_title
        article.current_title_version = version.version
        self.session.commit()
        return version

    def _current_model(self) -> str | None:
        try:
            _, profile = self.llm.get_binding(Stage.TITLE)
            return profile.model
        except Exception:  # noqa: BLE001
            return None
