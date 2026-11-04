"""Shared account positioning, entertainment scoring and article formats."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.models.system import Setting

ACCOUNT_PROFILE_KEY = "account_profile"


class AccountProfile(BaseModel):
    name: str = Field(default="AI 娱乐观察", min_length=1, max_length=80)
    audience: str = Field(default="对 AI 好奇、但不想读技术报告的普通读者", min_length=1)
    promise: str = Field(default="用真实、有趣的场景讲清 AI 新鲜事与使用体验", min_length=1)
    tone: str = Field(default="轻松、具体、有自嘲感；先讲人和场景，再解释技术", min_length=1)
    humor_boundaries: str = Field(default="不编造真实人物言论；不把未实测写成亲测；虚构场景明确标注", min_length=1)
    content_pillars: list[str] = Field(
        default_factory=lambda: ["AI 新鲜事轻解读", "AI 工具真实体验", "AI × 游戏、乒乓与文学脑洞"]
    )
    excluded_topics: list[str] = Field(default_factory=list)
    preferred_formats: list[str] = Field(
        default_factory=lambda: ["hot_take", "tool_test", "creative_experiment"]
    )
    default_domain: str = "有趣的 AI 产品、事件与使用场景"

    @field_validator("preferred_formats")
    @classmethod
    def valid_formats(cls, value: list[str]) -> list[str]:
        if not value or any(item not in CONTENT_FORMAT_KEYS for item in value):
            raise ValueError("preferred_formats 必须包含至少一种已支持的内容形式")
        return list(dict.fromkeys(value))

    def prompt_text(self) -> str:
        return "\n".join(
            [
                f"账号：{self.name}",
                f"目标读者：{self.audience}",
                f"内容承诺：{self.promise}",
                f"表达语气：{self.tone}",
                f"幽默边界：{self.humor_boundaries}",
                f"常写栏目：{'、'.join(self.content_pillars) or '未设置'}",
                f"排除话题：{'、'.join(self.excluded_topics) or '无'}",
            ]
        )


def load_account_profile(session: Session) -> AccountProfile:
    row = session.get(Setting, ACCOUNT_PROFILE_KEY)
    if row is None or not isinstance(row.value, dict):
        return AccountProfile()
    return AccountProfile.model_validate(row.value)


class ContentFormat(BaseModel):
    key: str
    label: str
    target_words: int
    outline_guidance: str
    writing_guidance: str


CONTENT_FORMATS = {
    item.key: item
    for item in [
        ContentFormat(
            key="hot_take",
            label="热点轻解读",
            target_words=900,
            outline_guidance="用一个具体场景或反差开头，再写发生了什么、为什么有意思、普通人会受到什么影响；安排 2-4 节。",
            writing_guidance="像给朋友讲一件有趣的新鲜事。笑点来自真实细节与反差，每段推进一个信息点。",
        ),
        ContentFormat(
            key="tool_test",
            label="AI 工具实测",
            target_words=1200,
            outline_guidance="按测试目标、实际操作、意外结果、适用人群组织 2-4 节；没有亲自测试的数据必须标为待验证。",
            writing_guidance="写清测试条件、输入、输出与局限。可以自嘲翻车经历，但没有实际测试时不得使用‘亲测’口吻。",
        ),
        ContentFormat(
            key="creative_experiment",
            label="AI 脑洞实验",
            target_words=800,
            outline_guidance="按设定、过程、反转或发现、现实启发组织 2-4 节；虚构演绎与真实材料分开。",
            writing_guidance="允许场景、对白和文学化表达；虚构桥段明确写明是模拟，不冒充真实采访或产品结果。",
        ),
    ]
}
CONTENT_FORMAT_KEYS = frozenset(CONTENT_FORMATS)


def get_content_format(key: str | None) -> ContentFormat:
    return CONTENT_FORMATS.get(key or "") or CONTENT_FORMATS["hot_take"]


SCORE_WEIGHTS = {
    "account_fit": 0.25,
    "novelty": 0.20,
    "relatability": 0.20,
    "demonstrability": 0.20,
    "humor_potential": 0.15,
}


def entertainment_score(scores: dict[str, float]) -> float:
    """Compute the published score from the five declared criteria."""
    return round(
        sum(max(0.0, min(100.0, float(scores.get(key, 0)))) * weight for key, weight in SCORE_WEIGHTS.items()),
        1,
    )
