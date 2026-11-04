"""Configuration and directory bootstrap tests."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT, Settings


def _clear_app_env(monkeypatch):
    for key in list(os.environ):
        if key.upper().startswith("APP_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults(monkeypatch):
    _clear_app_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.publish_confirmation is True
    assert settings.max_revisions == 3
    assert settings.effective_database_url.endswith("app.sqlite")
    assert settings.effective_checkpoint_url.endswith("checkpoints.sqlite")
    assert settings.feed_urls == []
    assert [spec.url for spec in settings.hot_source_specs] == [
        "https://www.qbitai.com/feed",
        "https://www.ifanr.com/feed",
        "https://sspai.com/feed",
        "https://www.producthunt.com/feed",
        "https://openai.com/news/rss.xml",
    ]
    assert settings.hot_source_specs[0].kind == "rss"
    assert settings.hot_source_specs[1].include_keywords
    assert "http://localhost:5173" in settings.allowed_origins
    assert settings.langfuse_enabled is False
    assert settings.langfuse_configured is False
    assert settings.langfuse_host == "http://127.0.0.1:3000"
    assert settings.langfuse_sample_rate == 1.0


def test_env_overrides_and_lists(monkeypatch, tmp_path):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_PORT", "9001")
    monkeypatch.setenv("APP_HOT_TOPICS_FEEDS", "https://a.example/feed, https://b.example/feed")
    monkeypatch.setenv("APP_CORS_ORIGINS", "http://a.test,http://b.test")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    settings = Settings(_env_file=None)
    assert settings.port == 9001
    assert settings.feed_urls == ["https://a.example/feed", "https://b.example/feed"]
    assert [spec.url for spec in settings.hot_source_specs] == [
        "https://a.example/feed",
        "https://b.example/feed",
    ]
    assert settings.allowed_origins == ["http://a.test", "http://b.test"]
    assert settings.effective_database_url == f"sqlite:///{(tmp_path / 'data' / 'app.sqlite').as_posix()}"


def test_relative_paths_resolve_to_project_root(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_DATA_DIR", "custom_data")
    settings = Settings(_env_file=None)
    assert settings.data_dir == (PROJECT_ROOT / "custom_data").resolve()


def test_hot_source_specs_prefer_json(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv(
        "APP_HOT_TOPIC_SOURCES",
        '[{"name": "列表页", "type": "html", "url": "https://example.com/news",'
        ' "item_selector": "article", "title_selector": "h2 a", "include_keywords": ["AI"],'
        ' "match_summary": true, "priority_keywords": ["游戏"]}]',
    )
    monkeypatch.setenv("APP_HOT_TOPICS_FEEDS", "https://legacy.example/feed")
    settings = Settings(_env_file=None)
    specs = settings.hot_source_specs
    assert len(specs) == 1
    assert specs[0].name == "列表页"
    assert specs[0].kind == "html"
    assert specs[0].item_selector == "article"
    assert specs[0].title_selector == "h2 a"
    assert specs[0].include_keywords == ("AI",)
    assert specs[0].match_summary is True
    assert specs[0].priority_keywords == ("游戏",)


def test_hot_source_specs_invalid_json_falls_back_to_legacy(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_HOT_TOPIC_SOURCES", "{not-json")
    monkeypatch.setenv("APP_HOT_TOPICS_FEEDS", "https://legacy.example/feed")
    settings = Settings(_env_file=None)
    assert [(spec.kind, spec.url) for spec in settings.hot_source_specs] == [
        ("rss", "https://legacy.example/feed")
    ]


def test_blank_urls_become_none(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_DATABASE_URL", "  ")
    monkeypatch.setenv("APP_CHECKPOINT_URL", "")
    settings = Settings(_env_file=None)
    assert settings.database_url is None
    assert settings.checkpoint_url is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("APP_PORT", "0"),
        ("APP_PORT", "70000"),
        ("APP_MAX_CONCURRENT_RUNS", "0"),
        ("APP_MAX_REVISIONS", "21"),
        ("APP_REVIEW_PASS_THRESHOLD", "101"),
        ("APP_METRICS_INTERVAL_HOURS", "0"),
        ("APP_LANGFUSE_SAMPLE_RATE", "1.5"),
        ("APP_LANGFUSE_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_ranges(monkeypatch, key, value):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_search_throttle_defaults(monkeypatch):
    _clear_app_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.search_throttle_enabled is True
    assert settings.search_min_interval_seconds == 1.0
    assert settings.search_cache_ttl_seconds == 600.0
    assert settings.search_cooldown_seconds == 60.0
    assert settings.search_max_requests_per_call == 6


def test_search_and_research_speed_defaults(monkeypatch):
    _clear_app_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.search_engines == "baidu,bing,360"
    assert settings.search_timeout_seconds == 5.0
    assert settings.search_max_retries == 0
    assert settings.search_budget_seconds == 12.0
    assert settings.deep_research_enabled is False
    assert settings.deep_research_max_steps == 5
    assert settings.deep_research_timeout_seconds == 25.0
    assert settings.deep_research_max_tokens == 20_000
    assert settings.research_llm_timeout_seconds == 15.0


def test_search_throttle_env_overrides(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_SEARCH_THROTTLE_ENABLED", "false")
    monkeypatch.setenv("APP_SEARCH_MIN_INTERVAL_SECONDS", "0.25")
    monkeypatch.setenv("APP_SEARCH_CACHE_TTL_SECONDS", "0")
    monkeypatch.setenv("APP_SEARCH_COOLDOWN_SECONDS", "30")
    monkeypatch.setenv("APP_SEARCH_MAX_REQUESTS_PER_CALL", "2")
    settings = Settings(_env_file=None)
    assert settings.search_throttle_enabled is False
    assert settings.search_min_interval_seconds == 0.25
    assert settings.search_cache_ttl_seconds == 0.0
    assert settings.search_cooldown_seconds == 30.0
    assert settings.search_max_requests_per_call == 2


def test_langfuse_configured_requires_all_fields(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("APP_LANGFUSE_HOST", "http://langfuse.internal:3000")
    monkeypatch.setenv("APP_LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("APP_LANGFUSE_SECRET_KEY", "sk-lf-test")
    settings = Settings(_env_file=None)
    assert settings.langfuse_configured is True

    monkeypatch.setenv("APP_LANGFUSE_SECRET_KEY", "  ")
    settings = Settings(_env_file=None)
    assert settings.langfuse_enabled is True
    assert settings.langfuse_configured is False


def test_short_secret_rejected(monkeypatch):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_SECRET_KEY", "short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_ensure_directories(monkeypatch, tmp_path):
    _clear_app_env(monkeypatch)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path / "logs"))
    settings = Settings(_env_file=None)
    settings.ensure_directories()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "data" / "backups").is_dir()
    assert (tmp_path / "logs").is_dir()
