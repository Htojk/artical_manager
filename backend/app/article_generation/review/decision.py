"""Route a human rejection to the stage that should regenerate the article."""

from __future__ import annotations

import logging

from app.core.constants import Stage
from app.core.llm import LLMService
from app.core.prompts import PromptLoader
from app.schemas.artifacts import RejectionRoute

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "你负责把人工驳回意见映射到最合适的返工阶段，只输出结构化结果。"
STAGE_MAP = {
    "research": Stage.RESEARCH,
    "outline": Stage.OUTLINE,
    "writing": Stage.WRITING,
}
RESEARCH_KEYWORDS = ("资料", "数据", "引用", "来源", "事实", "检索", "证据")
OUTLINE_KEYWORDS = ("结构", "大纲", "章节", "逻辑", "顺序", "框架")


def keyword_route(feedback: str) -> tuple[str, str]:
    """Deterministic fallback when the model cannot classify the feedback."""
    text = feedback or ""
    for keyword in RESEARCH_KEYWORDS:
        if keyword in text:
            return Stage.RESEARCH, f"意见包含「{keyword}」，回退资料搜索"
    for keyword in OUTLINE_KEYWORDS:
        if keyword in text:
            return Stage.OUTLINE, f"意见包含「{keyword}」，回退大纲"
    return Stage.WRITING, "意见不明确，默认回退写作"


class RejectionRouter:
    def __init__(self, llm: LLMService, *, prompts: PromptLoader | None = None) -> None:
        self.llm = llm
        self.prompts = prompts or PromptLoader()

    def route(
        self,
        *,
        article_id: str,
        title: str,
        feedback: str,
        verdict: str | None,
        rationale: str,
    ) -> tuple[str, str]:
        user = self.prompts.render(
            "review_rejection.md",
            title=title or "未命名",
            verdict=verdict or "unknown",
            rationale=rationale or "",
            feedback=feedback,
        )
        try:
            output = self.llm.structured(
                stage=Stage.REVIEW,
                schema=RejectionRoute,
                system=SYSTEM_PROMPT,
                user=user,
                article_id=article_id,
            )
            target = STAGE_MAP.get((output.rollback_to or "").strip().lower())
            if target is not None:
                return target, output.reason or "模型判定回退阶段"
            logger.warning("unexpected rejection target: %s", output.rollback_to)
        except Exception as exc:  # noqa: BLE001 - keyword fallback keeps the gate usable
            logger.warning("rejection routing failed, using keywords: %s", exc)
        return keyword_route(feedback)
