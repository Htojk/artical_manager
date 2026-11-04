"""Deterministic review verdict and rollback-target mapping."""

from __future__ import annotations

from app.core.constants import Stage

DEFAULT_WEIGHTS: dict[str, float] = {
    "fact": 0.30,
    "structure": 0.25,
    "readability": 0.20,
    "compliance": 0.15,
    "originality": 0.10,
}

DIMENSION_TO_STAGE: dict[str, str] = {
    "fact": Stage.RESEARCH,
    "structure": Stage.OUTLINE,
    "readability": Stage.WRITING,
    "compliance": Stage.WRITING,
    "originality": Stage.WRITING,
}

PASS_TOLERANCE = 5.0
SEVERE_LEVELS = {"critical", "major"}


def decide_verdict(
    total: float,
    threshold: float,
    scores: dict[str, dict],
    *,
    blocking: bool = False,
    tolerance: float = PASS_TOLERANCE,
) -> str:
    """Pass on threshold, or within tolerance when only minor issues exist."""
    if blocking:
        return "fail"
    if total >= threshold:
        return "pass"
    severe = any(
        str(issue.get("severity", "")).lower() in SEVERE_LEVELS
        for entry in scores.values()
        for issue in entry.get("issues", [])
    )
    if total >= threshold - tolerance and not severe:
        return "pass"
    return "fail"


def compute_total(scores: dict[str, dict], weights: dict[str, float] | None = None) -> float:
    active = weights or DEFAULT_WEIGHTS
    total = 0.0
    weight_sum = 0.0
    for dimension, weight in active.items():
        entry = scores.get(dimension)
        if entry is None:
            continue
        total += float(entry.get("score", 0)) * weight
        weight_sum += weight
    if weight_sum == 0:
        return 0.0
    return round(total / weight_sum, 2)


def determine_rollback(scores: dict[str, dict], verdict: str) -> str | None:
    if verdict == "pass":
        return None
    critical_dimensions = [
        name
        for name, entry in scores.items()
        if any(
            str(issue.get("severity", "")).lower() == "critical"
            for issue in entry.get("issues", [])
        )
    ]
    if "fact" in critical_dimensions:
        return Stage.RESEARCH
    if "structure" in critical_dimensions:
        return Stage.OUTLINE
    if critical_dimensions:
        return Stage.WRITING

    # No critical issues: route by the weakest weighted dimension.
    ranked = sorted(
        (
            (float(entry.get("score", 0)), name)
            for name, entry in scores.items()
            if name in DIMENSION_TO_STAGE
        ),
        key=lambda item: item[0],
    )
    if not ranked:
        return Stage.WRITING
    return DIMENSION_TO_STAGE[ranked[0][1]]
