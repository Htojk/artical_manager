"""Periodic evolution analysis that only creates pending suggestions."""

from __future__ import annotations

import logging

from app.core.llm import LLMService
from app.core.config import get_settings
from app.self_evolution.analyzer import EvolutionAnalyzer

logger = logging.getLogger(__name__)


def run_analysis_once(session_factory, llm: LLMService) -> int:
    settings = get_settings()
    if not settings.evolution_enabled:
        return 0
    with session_factory() as session:
        try:
            result = EvolutionAnalyzer(session, llm).analyze()
            logger.info("evolution analysis created %s suggestions", len(result.suggestions))
            return len(result.suggestions)
        except Exception:  # noqa: BLE001 - scheduled job must not crash the app
            logger.exception("evolution analysis failed")
            return 0
