"""Process-wide protection against hammering free search engines.

The guard is deliberately plain Python: per-engine pacing, a failure cooldown
and a small TTL cache.  Every ``HttpSearchTool`` in the process shares one
instance so that the research service and the deep agent cannot multiply
requests to the same engine.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from typing import Callable

from app.article_generation.research.search_engines import SearchResult

__all__ = ["SearchGuard", "get_search_guard", "reset_search_guard"]

logger = logging.getLogger(__name__)


def _copy_results(results: list[SearchResult]) -> list[SearchResult]:
    """Return independent copies so callers cannot mutate the cache."""
    return [replace(item) for item in results]


class SearchGuard:
    """Throttle, cool down and cache per-engine search calls."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        min_interval_seconds: float = 1.0,
        cache_ttl_seconds: float = 600.0,
        cooldown_seconds: float = 60.0,
        max_requests_per_call: int = 6,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.enabled = enabled
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.max_requests_per_call = max(1, int(max_requests_per_call))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}
        self._cooldown_until: dict[str, float] = {}
        self._cache: dict[tuple[str, str, int], tuple[float, list[SearchResult]]] = {}

    @classmethod
    def from_settings(cls, settings: object) -> "SearchGuard":
        return cls(
            enabled=bool(getattr(settings, "search_throttle_enabled", True)),
            min_interval_seconds=float(
                getattr(settings, "search_min_interval_seconds", 1.0)
            ),
            cache_ttl_seconds=float(
                getattr(settings, "search_cache_ttl_seconds", 600.0)
            ),
            cooldown_seconds=float(getattr(settings, "search_cooldown_seconds", 60.0)),
            max_requests_per_call=int(
                getattr(settings, "search_max_requests_per_call", 6)
            ),
        )

    # ---------------------------------------------------------------- cache

    @staticmethod
    def _key(engine: str, query: str, limit: int) -> tuple[str, str, int]:
        return (engine, " ".join(query.split()), int(limit))

    def get_cached(
        self, engine: str, query: str, limit: int
    ) -> list[SearchResult] | None:
        if not self.enabled or self.cache_ttl_seconds <= 0:
            return None
        key = self._key(engine, query, limit)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, results = entry
            if self._clock() >= expires_at:
                self._cache.pop(key, None)
                return None
            return _copy_results(results)

    def record_success(
        self,
        engine: str,
        query: str,
        limit: int,
        results: list[SearchResult],
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._cooldown_until.pop(engine, None)
            if self.cache_ttl_seconds <= 0:
                return
            self._cache[self._key(engine, query, limit)] = (
                self._clock() + self.cache_ttl_seconds,
                _copy_results(results),
            )

    # -------------------------------------------------------------- pacing

    def acquire(self, engine: str) -> bool:
        """Reserve a request slot for ``engine``.

        Returns ``False`` when the engine is cooling down.  Otherwise waits
        outside the lock until the per-engine minimum interval has elapsed.
        """
        if not self.enabled:
            return True
        with self._lock:
            now = self._clock()
            if now < self._cooldown_until.get(engine, 0.0):
                return False
            next_at = self._next_allowed.get(engine, now)
            wait = max(0.0, next_at - now)
            self._next_allowed[engine] = now + wait + self.min_interval_seconds
        if wait > 0:
            logger.debug("throttling %s for %.2fs", engine, wait)
            self._sleep(wait)
        return True

    def is_cooling(self, engine: str) -> bool:
        if not self.enabled or self.cooldown_seconds <= 0:
            return False
        with self._lock:
            return self._clock() < self._cooldown_until.get(engine, 0.0)

    def record_failure(self, engine: str) -> None:
        if not self.enabled or self.cooldown_seconds <= 0:
            return
        with self._lock:
            self._cooldown_until[engine] = self._clock() + self.cooldown_seconds

    # --------------------------------------------------------------- reset

    def reset(self) -> None:
        with self._lock:
            self._next_allowed.clear()
            self._cooldown_until.clear()
            self._cache.clear()


_default_guard: SearchGuard | None = None
_default_lock = threading.Lock()


def get_search_guard(settings: object | None = None) -> SearchGuard:
    """Return the process-wide guard, creating it from settings on first use."""
    global _default_guard
    if _default_guard is None:
        with _default_lock:
            if _default_guard is None:
                _default_guard = SearchGuard.from_settings(settings)
    return _default_guard


def reset_search_guard() -> None:
    """Drop the process-wide guard (used by tests and manual recovery)."""
    global _default_guard
    with _default_lock:
        _default_guard = None
