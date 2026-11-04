"""Scheduled jobs for metric collection and evolution analysis."""

from __future__ import annotations

import logging

from app.analytics.collector import MetricsCollector
from app.core.llm import LLMService
from app.core.security import CredentialService
from app.platforms.registry import PlatformRegistry
from app.self_evolution.scheduler import run_analysis_once

logger = logging.getLogger(__name__)


def collect_metrics_job(session_factory, registry: PlatformRegistry) -> int:
    with session_factory() as session:
        try:
            result = MetricsCollector(
                session, registry, CredentialService(session)
            ).collect()
            logger.info("metrics collected: %s", len(result.snapshots))
            return len(result.snapshots)
        except Exception:  # noqa: BLE001 - scheduled job must not crash
            logger.exception("metrics collection failed")
            return 0


def evolution_analysis_job(session_factory, llm: LLMService) -> int:
    return run_analysis_once(session_factory, llm)
