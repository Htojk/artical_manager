"""Choose one of the account's reusable WeChat covers from article tone."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from app.core.config import PROJECT_ROOT
from app.platforms.base import FormatResult

COVER_FILES = {
    "entertainment": "ai-entertainment.png",
    "technology": "ai-technology.png",
    "everyday_life": "ai-everyday-life.png",
    "workplace": "ai-workplace.png",
}
COVER_DIR = PROJECT_ROOT / "assets" / "wechat" / "covers"
DEFAULT_COVER_STYLE = "entertainment"

# Strong signals identify the subject; softer ones describe the writing tone.
STYLE_SIGNALS: dict[str, dict[str, int]] = {
    "entertainment": {
        "娱乐": 3, "游戏": 3, "虚构": 3, "剧场": 3, "脑洞": 3,
        "段子": 3, "吐槽": 3, "搞笑": 3, "幽默": 3, "甩锅": 3,
        "整活": 3, "反转": 2, "离谱": 2, "好笑": 2, "玩梗": 2,
    },
    "technology": {
        "技术": 3, "模型": 3, "算法": 3, "架构": 3, "开源": 3,
        "源码": 3, "算力": 3, "芯片": 3, "推理": 3, "训练": 3,
        "编程": 3, "协议": 2, "接口": 2, "代码": 2, "论文": 2,
        "api": 3, "mcp": 3, "rag": 3,
    },
    "everyday_life": {
        "民生": 3, "生活": 3, "家庭": 3, "老人": 3, "养老": 3,
        "医疗": 3, "医院": 3, "看病": 3, "社区": 3, "出行": 3,
        "政务": 3, "教育": 3, "学校": 3, "普通人": 2, "居民": 2,
        "消费": 2, "孩子": 2,
    },
    "workplace": {
        "职场": 3, "办公": 3, "会议": 3, "工作": 3, "效率": 3,
        "团队": 3, "同事": 3, "简历": 3, "求职": 3, "周报": 3,
        "会议纪要": 3, "协作": 2, "文档": 2, "项目": 2,
        "生产力": 2, "自动化": 2,
    },
}


def cover_path(style: str) -> Path:
    return COVER_DIR / COVER_FILES[style]


def select_cover_style(article: FormatResult) -> str:
    """Favor the title and summary over incidental words in the body."""
    body = unescape(re.sub(r"<[^>]+>", " ", article.content))[:1500]
    fields = (
        (article.title.lower(), 4),
        (article.summary.lower(), 2),
        (" ".join(article.tags).lower(), 2),
        (body.lower(), 1),
    )
    scores = {
        style: sum(weight * strength for text, weight in fields
                   for word, strength in signals.items() if word in text)
        for style, signals in STYLE_SIGNALS.items()
    }
    return max(scores, key=scores.get) if any(scores.values()) else DEFAULT_COVER_STYLE
