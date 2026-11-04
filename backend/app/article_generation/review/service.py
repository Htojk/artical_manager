"""Multi-dimension review with deterministic pass/fail and rollback routing."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.article_generation.quality import analyze_draft, analyze_evidence, validate_title
from app.article_generation.review.routing import (
    DEFAULT_WEIGHTS,
    decide_verdict,
    compute_total,
    determine_rollback,
)
from app.core.config import get_settings
from app.core.constants import Stage
from app.core.errors import NotFoundError, ValidationError
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.models.article import (
    Article,
    DraftVersion,
    Fact,
    OutlineVersion,
    ReviewReport,
    Source,
)
from app.models.system import Setting
from app.schemas.artifacts import ReviewOutput
from app.content_strategy import load_account_profile
from app.skills.manager import SkillManager

SYSTEM_PROMPT = "你是严格的内容审核编辑，只依据证据打分，并给出可执行的问题清单。"
EXPECTED_DIMENSIONS = ("fact", "structure", "readability", "compliance", "originality")
DIMENSION_ALIASES = {
    "fact": "fact",
    "facts": "fact",
    "factual": "fact",
    "accuracy": "fact",
    "事实": "fact",
    "事实性": "fact",
    "事实准确性": "fact",
    "准确性": "fact",
    "structure": "structure",
    "organization": "structure",
    "结构": "structure",
    "结构逻辑": "structure",
    "逻辑": "structure",
    "章节结构": "structure",
    "readability": "readability",
    "可读性": "readability",
    "表达": "readability",
    "表达清晰度": "readability",
    "compliance": "compliance",
    "合规": "compliance",
    "合规性": "compliance",
    "规范": "compliance",
    "originality": "originality",
    "原创性": "originality",
    "原创": "originality",
    "独创性": "originality",
}


def dimension_key(raw: str) -> str | None:
    """Map English/Chinese dimension aliases to the canonical keys."""
    normalized = re.sub(r"[\s_\-]+", "", (raw or "").strip().lower())
    return DIMENSION_ALIASES.get(normalized)


@dataclass
class ReviewResult:
    report: ReviewReport
    scores: dict
    total: float
    verdict: str
    rollback_to: str | None


def latest_failed_issues(session: Session, article_id: str) -> list[dict]:
    """Flatten the newest failed report into actionable issue dicts."""
    report = session.scalar(
        select(ReviewReport)
        .where(ReviewReport.article_id == article_id, ReviewReport.verdict == "fail")
        .order_by(ReviewReport.created_at.desc())
    )
    if report is None or not isinstance(report.scores, dict):
        return []
    issues: list[dict] = []
    for dimension, entry in report.scores.items():
        for item in entry.get("issues", []):
            issues.append(
                {
                    "dimension": dimension,
                    "location": str(item.get("location", "")),
                    "description": str(item.get("description", "")),
                    "severity": str(item.get("severity", "minor")),
                }
            )
    return issues


class ReviewService:
    def __init__(
        self,
        session: Session,
        llm: LLMService,
        *,
        prompts: PromptLoader | None = None,
        weights: dict[str, float] | None = None,
        threshold: float | None = None,
        skills: SkillManager | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.skills = skills
        self.weights = weights or DEFAULT_WEIGHTS
        self.threshold = self._resolve_threshold() if threshold is None else threshold

    def _resolve_threshold(self) -> float:
        """Read the runtime threshold, falling back to config when missing/invalid."""
        default = get_settings().review_pass_threshold
        row = self.session.get(Setting, "review_pass_threshold")
        value = row.value if row is not None else None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if 0 <= parsed <= 100 else default

    def latest_draft(self, article_id: str) -> DraftVersion:
        draft = self.session.scalar(
            select(DraftVersion)
            .where(DraftVersion.article_id == article_id)
            .order_by(DraftVersion.version.desc())
        )
        if draft is None:
            raise ValidationError("尚无正文可审核")
        return draft

    def history(self, article_id: str) -> list[ReviewReport]:
        return list(
            self.session.scalars(
                select(ReviewReport)
                .where(ReviewReport.article_id == article_id)
                .order_by(ReviewReport.created_at)
            )
        )

    def review(self, article_id: str) -> ReviewResult:
        article = self.session.get(Article, article_id)
        if article is None:
            raise NotFoundError(f"文章不存在: {article_id}")
        draft = self.latest_draft(article_id)
        sources = list(
            self.session.scalars(
                select(Source).where(Source.article_id == article_id).order_by(Source.fetched_at)
            )
        )
        facts = list(
            self.session.scalars(
                select(Fact).where(Fact.article_id == article_id).order_by(Fact.created_at)
            )
        )
        outline = self.session.scalar(
            select(OutlineVersion)
            .where(OutlineVersion.article_id == article_id)
            .order_by(OutlineVersion.version.desc())
        )
        source_index = {source.id: index for index, source in enumerate(sources, start=1)}
        targets = int((outline.content if outline else {}).get("target_words", 0) or 0)
        draft_audit = analyze_draft(draft.content_md, sources, target_words=targets)
        evidence = analyze_evidence(sources, facts)
        title_issues = validate_title(article.title, list(article.target_platforms or []))
        prompt = self.prompts.render(
            "review.md",
            account_profile=load_account_profile(self.session).prompt_text(),
            platforms=", ".join(article.target_platforms or []) or "通用",
            weights=self.weights,
            title=article.title,
            draft=draft.content_md,
            outline=outline.content if outline else {},
            facts=[
                {
                    "statement": fact.statement,
                    "source_index": source_index.get(fact.source_id, 0),
                    "status": fact.status,
                }
                for fact in facts
            ],
            sources=[
                {
                    "index": index,
                    "title": source.title,
                    "url": source.url,
                    "credibility": source.credibility,
                    "published_at": source.published_at,
                }
                for index, source in enumerate(sources, start=1)
            ],
            quality={
                "draft": draft_audit,
                "evidence": evidence,
                "title_issues": title_issues,
            },
        )
        output = self.llm.structured(
            stage=Stage.REVIEW,
            schema=ReviewOutput,
            system=(
                self.skills.system_prompt(Stage.REVIEW, SYSTEM_PROMPT)
                if self.skills is not None
                else SYSTEM_PROMPT
            ),
            user=prompt,
            article_id=article_id,
        )
        scores = self._normalize(output)
        blocking = self._apply_quality_gates(scores, draft_audit, title_issues)
        total = compute_total(scores, self.weights)
        verdict = decide_verdict(total, self.threshold, scores, blocking=blocking)
        rollback_to = determine_rollback(scores, verdict)
        config_version = hashlib.sha256(
            json.dumps(
                {"weights": self.weights, "threshold": self.threshold},
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()[:12]
        rationale = output.summary
        if verdict == "fail":
            critical = [
                issue["description"]
                for entry in scores.values()
                for issue in entry.get("issues", [])
                if str(issue.get("severity", "")).lower() == "critical"
            ]
            if critical:
                rationale = (rationale + "；关键问题：" + "；".join(critical[:3])).strip("；")
        report = ReviewReport(
            article_id=article_id,
            draft_version_id=draft.id,
            scores=scores,
            total=total,
            verdict=verdict,
            rollback_to=rollback_to,
            rationale=rationale,
            model=self._current_model(),
            config_version=config_version,
        )
        self.session.add(report)
        self.session.commit()
        return ReviewResult(
            report=report,
            scores=scores,
            total=total,
            verdict=verdict,
            rollback_to=rollback_to,
        )

    @staticmethod
    def _issue(entry: dict, description: str, severity: str, location: str = "") -> None:
        existing = {item.get("description") for item in entry.get("issues", [])}
        if description not in existing:
            entry.setdefault("issues", []).append(
                {
                    "location": location,
                    "description": description,
                    "severity": severity,
                }
            )

    def _apply_quality_gates(
        self, scores: dict, audit: dict, title_issues: list[str]
    ) -> bool:
        """Turn objective citation/title defects into issues; return True if blocking."""
        blocking = False
        fact = scores.get("fact")
        if fact is not None and audit["source_count"]:
            dangling = audit["dangling_citations"]
            total_refs = audit.get("citation_count", 0)
            invalid_ratio = len(dangling) / total_refs if total_refs else 0.0
            if not audit["valid_citation_count"]:
                self._issue(fact, "正文没有引用任何有效来源", "critical")
                fact["score"] = min(float(fact.get("score", 0)), 40.0)
                blocking = True
            elif invalid_ratio > 0.5:
                refs = "、".join(str(ref) for ref in dangling)
                self._issue(
                    fact,
                    f"无效引用序号占比超过一半: {refs}",
                    "major",
                )
                fact["score"] = min(float(fact.get("score", 0)), 60.0)
                blocking = True
            elif dangling:
                refs = "、".join(str(ref) for ref in dangling)
                self._issue(fact, f"正文引用了不存在的来源序号: {refs}", "major")
                fact["score"] = min(float(fact.get("score", 0)), 70.0)
            elif audit["cited_source_count"] / audit["source_count"] < 0.3:
                self._issue(
                    fact,
                    f"仅引用 {audit['cited_source_count']} / {audit['source_count']} 个来源，覆盖不足",
                    "minor",
                )
        compliance = scores.get("compliance")
        if compliance is not None and title_issues:
            blocking_titles = [item for item in title_issues if "标题过短" not in item]
            if blocking_titles:
                self._issue(compliance, "；".join(blocking_titles), "major", "标题")
                compliance["score"] = min(float(compliance.get("score", 0)), 70.0)
                blocking = True
            short_titles = [item for item in title_issues if "标题过短" in item]
            if short_titles:
                self._issue(compliance, "；".join(short_titles), "minor", "标题")
        return blocking

    def _normalize(self, output: ReviewOutput) -> dict:
        scores: dict[str, dict] = {}
        for dimension in output.dimensions:
            name = dimension_key(dimension.dimension)
            if name is None:
                continue
            scores[name] = {
                "score": dimension.score,
                "issues": [issue.model_dump() for issue in dimension.issues],
                "suggestions": list(dimension.suggestions),
            }
        for name in EXPECTED_DIMENSIONS:
            if name not in scores:
                scores[name] = {
                    "score": 0.0,
                    "issues": [
                        {
                            "location": "",
                            "description": f"审核未返回 {name} 维度结果",
                            "severity": "major",
                        }
                    ],
                    "suggestions": [],
                }
        return scores

    def _current_model(self) -> str | None:
        try:
            _, profile = self.llm.get_binding(Stage.REVIEW)
            return profile.model
        except Exception:  # noqa: BLE001
            return None
