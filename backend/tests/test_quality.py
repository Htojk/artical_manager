"""Deterministic quality signals used by generation and review."""

from __future__ import annotations

from types import SimpleNamespace

from app.article_generation.quality import (
    analyze_draft,
    analyze_evidence,
    count_words,
    title_limit,
    validate_title,
)
from app.article_generation.review.decision import keyword_route
from app.article_generation.review.routing import decide_verdict
from app.article_generation.review.service import EXPECTED_DIMENSIONS, ReviewService
from app.core.config import get_settings
from app.schemas.artifacts import ReviewDimension, ReviewOutput


def _source(url: str, credibility: str = "medium") -> SimpleNamespace:
    return SimpleNamespace(url=url, credibility=credibility)


def _fact(statement: str, status: str = "verified", source_id: str | None = "s1"):
    return SimpleNamespace(statement=statement, status=status, source_id=source_id)


def test_count_words_counts_chinese_chars_and_latin_tokens():
    assert count_words("AI 工程 实践") == 5
    assert count_words("") == 0


def test_title_rules_respect_platform_and_clickbait():
    assert title_limit(["wechat", "zhihu"]) == 64
    assert title_limit([]) == 120
    assert validate_title("AI 工程实践的三条经验", ["wechat"]) == []
    assert any("上限" in item for item in validate_title("长" * 65, ["wechat"]))
    assert any("标题党" in item for item in validate_title("震惊！AI 要变天了"))
    assert "标题过短" in validate_title("AI")


def test_evidence_flags_unverified_and_single_domain():
    sources = [_source("https://example.com/a"), _source("https://example.com/b")]
    facts = [_fact("有来源的事实"), _fact("没有来源的事实", status="unverified")]
    report = analyze_evidence(sources, facts)
    assert report["verified_fact_count"] == 1
    assert report["verified_ratio"] == 0.5
    assert report["low_confidence"] is False
    assert any("同一域名" in item for item in report["issues"])
    assert any("高可信度" in item for item in report["issues"])

    assert analyze_evidence([], [])["low_confidence"] is True


def test_draft_audit_reports_dangling_citations_and_uncited_sections():
    sources = [_source("https://a.example/1"), _source("https://b.example/2")]
    content = (
        "## 背景\n\n"
        + "背景说明。" * 20
        + "引用 [1]。\n\n## 结论\n\n"
        + "结论说明。" * 25
        + "引用 [5]。\n\n## 方案\n\n"
        + "方案说明。" * 20
        + "\n"
    )
    report = analyze_draft(content, sources, target_words=100)
    assert report["valid_citation_count"] == 1
    assert report["dangling_citations"] == [5]
    assert report["cited_source_count"] == 1
    assert any("无效引用" in item for item in report["issues"])
    assert any("字数偏离" in item for item in report["issues"])
    assert report["uncited_sections"]


def test_draft_audit_without_sources_does_not_require_citations():
    report = analyze_draft("## 一节\n\n" + "内容。" * 200, [])
    assert report["source_count"] == 0
    assert report["dangling_citations"] == []


class _SettingSession:
    def __init__(self, value):
        self.value = value

    def get(self, model, key):  # noqa: ARG002 - stub matches Session.get
        return None if self.value is _MISSING else SimpleNamespace(value=self.value)


_MISSING = object()


def test_review_threshold_reads_settings_table_and_falls_back():
    assert ReviewService(_SettingSession(70), None).threshold == 70
    assert ReviewService(_SettingSession("82.5"), None).threshold == 82.5
    default = get_settings().review_pass_threshold
    assert ReviewService(_SettingSession("bad"), None).threshold == default
    assert ReviewService(_SettingSession(120), None).threshold == default
    assert ReviewService(_SettingSession(_MISSING), None).threshold == default
    assert ReviewService(_SettingSession(70), None, threshold=90).threshold == 90


def _score_entry(score: float = 80, severity: str = "minor") -> dict:
    return {
        "score": score,
        "issues": [{"location": "", "description": "问题", "severity": severity}],
        "suggestions": [],
    }


def test_review_verdict_uses_tolerance_only_for_minor_issues():
    scores = {"fact": _score_entry(71)}
    assert decide_verdict(72, 75, scores) == "pass"
    assert decide_verdict(71, 75, scores) == "pass"
    assert decide_verdict(69, 75, scores) == "fail"

    major = {"fact": _score_entry(72, "major")}
    assert decide_verdict(72, 75, major) == "fail"
    critical = {"fact": _score_entry(72, "critical")}
    assert decide_verdict(72, 75, critical) == "fail"

    assert decide_verdict(90, 75, scores, blocking=True) == "fail"


def _gate_scores() -> dict:
    return {
        name: {"score": 85.0, "issues": [], "suggestions": []}
        for name in ("fact", "structure", "readability", "compliance", "originality")
    }


def _audit(**overrides) -> dict:
    audit = {
        "source_count": 3,
        "citation_count": 2,
        "valid_citation_count": 2,
        "cited_source_count": 2,
        "dangling_citations": [],
    }
    audit.update(overrides)
    return audit


def test_quality_gate_keeps_few_dangling_citations_non_blocking():
    scores = _gate_scores()
    blocking = ReviewService(_SettingSession(75), None)._apply_quality_gates(
        scores, _audit(dangling_citations=[9]), []
    )
    assert blocking is False
    assert scores["fact"]["score"] == 70.0
    assert scores["fact"]["issues"][0]["severity"] == "major"


def test_quality_gate_blocks_when_no_valid_citations_or_mostly_invalid():
    scores = _gate_scores()
    blocking = ReviewService(_SettingSession(75), None)._apply_quality_gates(
        scores, _audit(citation_count=2, valid_citation_count=0, dangling_citations=[8, 9]), []
    )
    assert blocking is True
    assert scores["fact"]["issues"][0]["severity"] == "critical"
    assert scores["fact"]["score"] == 40.0

    scores = _gate_scores()
    blocking = ReviewService(_SettingSession(75), None)._apply_quality_gates(
        scores,
        _audit(citation_count=3, valid_citation_count=1, dangling_citations=[8, 9]),
        [],
    )
    assert blocking is True
    assert scores["fact"]["issues"][0]["severity"] == "major"
    assert scores["fact"]["score"] == 60.0


def test_review_normalizes_chinese_and_case_dimension_aliases():
    output = ReviewOutput(
        dimensions=[
            ReviewDimension(dimension="事实准确性", score=88),
            ReviewDimension(dimension=" Structure ", score=80),
            ReviewDimension(dimension="可读性", score=90),
            ReviewDimension(dimension="合规性", score=85),
            ReviewDimension(dimension="Originality", score=70),
            ReviewDimension(dimension="无法识别的维度", score=0),
        ]
    )
    scores = ReviewService(_SettingSession(75), None)._normalize(output)
    assert set(scores) == set(EXPECTED_DIMENSIONS)
    assert scores["fact"]["score"] == 88
    assert scores["structure"]["score"] == 80
    assert scores["readability"]["score"] == 90
    assert scores["compliance"]["score"] == 85
    assert scores["originality"]["score"] == 70
    assert all(entry["issues"] == [] for entry in scores.values())


def test_rejection_keywords_route_to_research_outline_or_writing():
    from app.core.constants import Stage

    assert keyword_route("数据来源不可靠，需要补充权威资料")[0] == Stage.RESEARCH
    assert keyword_route("章节顺序混乱，需要调整大纲")[0] == Stage.OUTLINE
    assert keyword_route("整体表达太啰嗦")[0] == Stage.WRITING


def test_quality_gate_blocks_oversized_title_but_not_short_title():
    scores = _gate_scores()
    blocking = ReviewService(_SettingSession(75), None)._apply_quality_gates(
        scores, _audit(), ["标题超过平台上限 64 字"]
    )
    assert blocking is True
    assert scores["compliance"]["score"] == 70.0
    assert scores["compliance"]["issues"][0]["severity"] == "major"

    scores = _gate_scores()
    blocking = ReviewService(_SettingSession(75), None)._apply_quality_gates(
        scores, _audit(), ["标题过短"]
    )
    assert blocking is False
    assert scores["compliance"]["score"] == 85.0
    assert scores["compliance"]["issues"][0]["severity"] == "minor"
