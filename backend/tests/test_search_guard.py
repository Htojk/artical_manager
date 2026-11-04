"""SearchGuard: pacing, cooldown, TTL cache and defensive copies."""

from __future__ import annotations

from app.article_generation.research.search_engines import SearchResult
from app.article_generation.research.search_guard import SearchGuard


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _guard(**overrides) -> tuple[SearchGuard, FakeClock]:
    clock = FakeClock()
    options = {
        "min_interval_seconds": 2.0,
        "cache_ttl_seconds": 10.0,
        "cooldown_seconds": 5.0,
        "clock": clock,
        "sleep": clock.sleep,
    }
    options.update(overrides)
    return SearchGuard(**options), clock


def _results() -> list[SearchResult]:
    return [SearchResult(title="原文", url="https://example.com/a", snippet="摘要")]


def test_acquire_paces_only_the_same_engine():
    guard, clock = _guard()

    assert guard.acquire("baidu") is True
    assert clock.now == 0.0

    assert guard.acquire("baidu") is True
    assert clock.now == 2.0

    # Another engine has its own slot and does not wait for Baidu.
    assert guard.acquire("bing") is True
    assert clock.now == 2.0

    assert guard.acquire("baidu") is True
    assert clock.now == 4.0


def test_zero_interval_never_sleeps():
    guard, clock = _guard(min_interval_seconds=0)
    for _ in range(3):
        assert guard.acquire("baidu") is True
    assert clock.now == 0.0


def test_failure_cools_down_then_recovers():
    guard, clock = _guard()

    guard.record_failure("baidu")
    assert guard.is_cooling("baidu") is True
    assert guard.acquire("baidu") is False
    assert clock.now == 0.0, "cooldown skip must not send or wait"

    clock.now = 5.0
    assert guard.is_cooling("baidu") is False
    assert guard.acquire("baidu") is True


def test_success_clears_cooldown():
    guard, _ = _guard()
    guard.record_failure("360")
    assert guard.is_cooling("360") is True

    guard.record_success("360", "q", 3, _results())
    assert guard.is_cooling("360") is False
    assert guard.acquire("360") is True


def test_cache_hit_and_expiry():
    guard, clock = _guard()

    guard.record_success("bing", "  AI   Agent ", 3, _results())
    hit = guard.get_cached("bing", "AI Agent", 3)  # whitespace-normalised key
    assert hit is not None
    assert [item.url for item in hit] == ["https://example.com/a"]

    clock.now = 9.9
    assert guard.get_cached("bing", "AI Agent", 3) is not None

    clock.now = 10.0
    assert guard.get_cached("bing", "AI Agent", 3) is None


def test_cache_returns_defensive_copies():
    guard, _ = _guard()
    guard.record_success("360", "q", 2, _results())

    first = guard.get_cached("360", "q", 2)
    assert first is not None
    first[0].title = "被调用方修改"
    first[0].url = "https://example.com/mutated"

    second = guard.get_cached("360", "q", 2)
    assert second is not None
    assert second[0].title == "原文"
    assert second[0].url == "https://example.com/a"


def test_zero_ttl_disables_cache():
    guard, _ = _guard(cache_ttl_seconds=0)
    guard.record_success("baidu", "q", 3, _results())
    assert guard.get_cached("baidu", "q", 3) is None


def test_disabled_guard_does_nothing():
    guard, clock = _guard(enabled=False, min_interval_seconds=10)

    for _ in range(3):
        assert guard.acquire("baidu") is True
    assert clock.now == 0.0

    guard.record_success("baidu", "q", 3, _results())
    assert guard.get_cached("baidu", "q", 3) is None

    guard.record_failure("baidu")
    assert guard.is_cooling("baidu") is False
    assert guard.acquire("baidu") is True


def test_reset_clears_state():
    guard, _ = _guard()
    guard.acquire("baidu")
    guard.record_failure("bing")
    guard.record_success("360", "q", 1, _results())

    guard.reset()

    assert guard.is_cooling("bing") is False
    assert guard.get_cached("360", "q", 1) is None
    # A reset also clears the pacing slot, so the next call is immediate.
    assert guard.acquire("baidu") is True


def test_from_settings_reads_protection_values():
    class Settings:
        search_throttle_enabled = False
        search_min_interval_seconds = 0.5
        search_cache_ttl_seconds = 0
        search_cooldown_seconds = 12
        search_max_requests_per_call = 2

    guard = SearchGuard.from_settings(Settings())
    assert guard.enabled is False
    assert guard.min_interval_seconds == 0.5
    assert guard.cache_ttl_seconds == 0.0
    assert guard.cooldown_seconds == 12.0
    assert guard.max_requests_per_call == 2
