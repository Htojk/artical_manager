"""Deterministic quality signals shared by generation and review stages.

The LLM judges tone and argument quality; these checks provide objective
evidence (citations, word targets, title limits, source coverage) so a model
cannot silently pass an obviously broken article.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

CITATION_PATTERN = re.compile(r"\[(\d+)\]")
HEADING_PATTERN = re.compile(r"^(#{2,6})\s+(.+?)\s*$", re.MULTILINE)
WORD_PATTERN = re.compile(r"[一-鿿]|[A-Za-z0-9]+")
BANNED_TITLE_PHRASES = (
    "震惊",
    "必看",
    "惊呆",
    "炸裂",
    "史上最",
    "99%的人",
    "不转不是",
    "惊天",
)
PLATFORM_TITLE_LIMITS = {
    "wechat": 64,
    "zhihu": 100,
    "csdn": 100,
    "juejin": 80,
    "mock": 120,
}
DEFAULT_TITLE_LIMIT = 120


def count_words(text: str) -> int:
    return len(WORD_PATTERN.findall(text or ""))


def title_limit(platforms: list[str] | tuple[str, ...] = ()) -> int:
    limits = [PLATFORM_TITLE_LIMITS[item] for item in platforms if item in PLATFORM_TITLE_LIMITS]
    return min(limits) if limits else DEFAULT_TITLE_LIMIT


def validate_title(title: str, platforms: list[str] | tuple[str, ...] = ()) -> list[str]:
    cleaned = (title or "").strip()
    issues: list[str] = []
    if len(cleaned) < 4:
        issues.append("标题过短")
    limit = title_limit(platforms)
    if len(cleaned) > limit:
        issues.append(f"标题超过平台上限 {limit} 字")
    for phrase in BANNED_TITLE_PHRASES:
        if phrase in cleaned:
            issues.append(f"标题包含标题党措辞「{phrase}」")
    return issues


def analyze_evidence(sources: list, facts: list) -> dict:
    """Summarise whether facts are traceable to credible sources."""
    fact_count = len([fact for fact in facts if (fact.statement or "").strip()])
    verified = [
        fact
        for fact in facts
        if (fact.statement or "").strip() and fact.status == "verified" and fact.source_id
    ]
    high = [source for source in sources if source.credibility == "high"]
    domains = {
        urlparse(source.url).netloc.lower()
        for source in sources
        if getattr(source, "url", "")
    }
    ratio = round(len(verified) / fact_count, 2) if fact_count else 0.0
    issues: list[str] = []
    if not fact_count:
        issues.append("没有提取到可验证事实")
    elif ratio < 0.5:
        issues.append("超过一半的事实没有来源支撑")
    if sources and not high:
        issues.append("缺少高可信度来源")
    if len(domains) == 1:
        issues.append("所有来源来自同一域名，存在单一来源风险")
    return {
        "source_count": len(sources),
        "fact_count": fact_count,
        "verified_fact_count": len(verified),
        "verified_ratio": ratio,
        "high_credibility_sources": len(high),
        "distinct_domains": len(domains),
        "low_confidence": not verified or ratio < 0.5,
        "issues": issues,
    }


def analyze_draft(
    content_md: str,
    sources: list,
    *,
    target_words: int = 0,
) -> dict:
    """Collect citation, structure and length signals for a draft."""
    content = content_md or ""
    words = count_words(content)
    headings = [match.group(2).strip() for match in HEADING_PATTERN.finditer(content)]
    refs = [int(ref) for ref in CITATION_PATTERN.findall(content)]
    valid_range = set(range(1, len(sources) + 1))
    dangling = sorted({ref for ref in refs if ref not in valid_range})
    valid_refs = [ref for ref in refs if ref in valid_range]
    cited_sources = len(set(valid_refs))
    sections = _sections(content)
    uncited = [
        heading
        for heading, body in sections
        if heading and count_words(body) >= 60 and not CITATION_PATTERN.search(body)
    ]
    issues: list[str] = []
    if len(sources) and not valid_refs:
        issues.append("正文没有引用任何有效来源")
    if dangling:
        issues.append(f"存在 {len(dangling)} 个无效引用序号")
    if len(sources) and cited_sources / len(sources) < 0.3:
        issues.append("引用来源覆盖不足 30%")
    if len(headings) < 2:
        issues.append("正文少于两个二级章节")
    if words < 300:
        issues.append("正文过短，可能缺少充分论证")
    if uncited:
        issues.append(f"{len(uncited)} 个章节没有引用任何来源")
    deviation = None
    if target_words > 0:
        deviation = round((words - target_words) / target_words, 2)
        if abs(deviation) > 0.35:
            issues.append(f"字数偏离目标 {target_words} 字超过 35%")
    return {
        "word_count": words,
        "target_words": target_words,
        "word_deviation": deviation,
        "heading_count": len(headings),
        "headings": headings,
        "citation_count": len(refs),
        "valid_citation_count": len(valid_refs),
        "dangling_citations": dangling,
        "cited_source_count": cited_sources,
        "source_count": len(sources),
        "uncited_sections": uncited,
        "issues": issues,
    }


def _sections(content: str) -> list[tuple[str, str]]:
    matches = list(HEADING_PATTERN.finditer(content))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections.append((match.group(2).strip(), content[match.end() : end]))
    return sections
