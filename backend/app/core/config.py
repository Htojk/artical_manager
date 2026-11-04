"""Application configuration loaded from environment variables and .env."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
logger = logging.getLogger(__name__)

DEFAULT_HOT_SOURCE_URL = "https://www.qbitai.com/feed"
AI_TOPIC_KEYWORDS = (
    "AI", "人工智能", "大模型", "智能体", "ChatGPT", "Claude", "Gemini",
    "豆包", "DeepSeek", "AIGC", "生成式", "机器人", "GPT", "Agent",
    "LLM", "Sora", "文生视频", "文生图", "MCP",
)
ACCOUNT_INTEREST_KEYWORDS = (
    "游戏", "文学", "小说", "写作", "音乐", "电影", "视频", "创作", "生活",
    "体验", "普通人", "家庭", "老人", "孩子", "社交", "聊天", "语音",
    "乒乓", "演唱会", "抢票", "有趣", "搞笑", "脑洞", "翻车",
    "game", "story", "writing", "music", "video", "creative", "creator",
    "family", "personal", "social", "voice", "fun", "meme", "companion",
)


@dataclass(frozen=True)
class HotSourceSpec:
    """One configured hot-topic source (RSS/Atom or HTML list page)."""

    name: str
    kind: str
    url: str
    item_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    content_selector: str = ""
    include_keywords: tuple[str, ...] = ()
    match_summary: bool = False
    priority_keywords: tuple[str, ...] = ()


DEFAULT_HOT_SOURCE_SPECS: tuple[HotSourceSpec, ...] = (
    HotSourceSpec(name="量子位", kind="rss", url=DEFAULT_HOT_SOURCE_URL,
                  include_keywords=AI_TOPIC_KEYWORDS,
                  priority_keywords=ACCOUNT_INTEREST_KEYWORDS),
    HotSourceSpec(name="爱范儿", kind="rss", url="https://www.ifanr.com/feed",
                  include_keywords=AI_TOPIC_KEYWORDS,
                  priority_keywords=ACCOUNT_INTEREST_KEYWORDS),
    HotSourceSpec(name="少数派", kind="rss", url="https://sspai.com/feed",
                  include_keywords=AI_TOPIC_KEYWORDS,
                  priority_keywords=ACCOUNT_INTEREST_KEYWORDS),
    HotSourceSpec(name="Product Hunt", kind="rss", url="https://www.producthunt.com/feed",
                  include_keywords=("AI", "Agent", "Agents", "GPT", "LLM", "generative", "MCP"),
                  match_summary=True, priority_keywords=ACCOUNT_INTEREST_KEYWORDS),
    HotSourceSpec(name="OpenAI 官方", kind="rss", url="https://openai.com/news/rss.xml",
                  include_keywords=("ChatGPT", "Codex", "Sora", "GPT", "Agent", "image", "video", "voice", "creative", "education", "family"),
                  priority_keywords=ACCOUNT_INTEREST_KEYWORDS),
)


def _spec_from_dict(item: object) -> HotSourceSpec | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    kind = str(item.get("type") or "rss").strip().lower()
    if kind not in {"rss", "html"}:
        return None
    keywords = item.get("include_keywords")
    include_keywords = (
        tuple(str(word).strip() for word in keywords if str(word).strip())
        if isinstance(keywords, list) else ()
    )
    priorities = item.get("priority_keywords")
    priority_keywords = (
        tuple(str(word).strip() for word in priorities if str(word).strip())
        if isinstance(priorities, list) else ()
    )
    return HotSourceSpec(
        name=str(item.get("name") or urlparse(url).netloc or url).strip(),
        kind=kind,
        url=url,
        item_selector=str(item.get("item_selector") or "").strip(),
        title_selector=str(item.get("title_selector") or "").strip(),
        link_selector=str(item.get("link_selector") or "").strip(),
        content_selector=str(item.get("content_selector") or "").strip(),
        include_keywords=include_keywords,
        match_summary=item.get("match_summary") is True,
        priority_keywords=priority_keywords,
    )


def parse_hot_source_specs(raw: str, legacy_feeds: list[str]) -> list[HotSourceSpec]:
    """Resolve configured sources: JSON -> legacy feeds -> curated default set."""
    raw = (raw or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("APP_HOT_TOPIC_SOURCES is not valid JSON: %s", exc)
        else:
            if isinstance(payload, list):
                specs = [spec for item in payload if (spec := _spec_from_dict(item)) is not None]
                if specs:
                    return specs
            else:
                logger.warning("APP_HOT_TOPIC_SOURCES must be a JSON array")
    if legacy_feeds:
        return [
            HotSourceSpec(name=urlparse(url).netloc or url, kind="rss", url=url)
            for url in legacy_feeds
        ]
    return list(DEFAULT_HOT_SOURCE_SPECS)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="APP_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Article Autopilot"
    env: str = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    frontend_port: int = Field(default=5173, ge=1, le=65535)

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str | None = None
    checkpoint_url: str | None = None
    skills_dir: Path = PROJECT_ROOT / "skills"
    prompts_dir: Path = PROJECT_ROOT / "backend" / "app" / "prompts"
    log_dir: Path = PROJECT_ROOT / "logs"

    secret_key: str | None = None
    max_concurrent_runs: int = Field(default=1, ge=1, le=8)
    publish_confirmation: bool = True
    max_revisions: int = Field(default=3, ge=0, le=20)
    review_pass_threshold: float = Field(default=75.0, ge=0, le=100)

    metrics_interval_hours: float = Field(default=6.0, gt=0)
    evolution_interval_hours: float = Field(default=168.0, gt=0)
    evolution_enabled: bool = True

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_input_price_per_1k: float | None = None
    llm_output_price_per_1k: float | None = None
    llm_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # Free HTML search engines, tried in order when no endpoint is configured.
    search_engines: str = "baidu,bing,360"
    # Optional JSON search endpoint; when set it is tried before the free engines.
    search_endpoint: str | None = None
    search_api_key: str | None = None
    search_timeout_seconds: float = Field(default=5.0, gt=0)
    search_max_retries: int = Field(default=0, ge=0, le=5)
    # Wall-clock cap for one search query across all engines/retries/redirects.
    search_budget_seconds: float = Field(default=12.0, gt=0)
    # In-process protection against hammering the free search engines.
    search_throttle_enabled: bool = True
    search_min_interval_seconds: float = Field(default=1.0, ge=0, le=60)
    search_cache_ttl_seconds: float = Field(default=600.0, ge=0)
    search_cooldown_seconds: float = Field(default=60.0, ge=0)
    search_max_requests_per_call: int = Field(default=6, ge=1, le=50)
    hot_topics_feeds: str = ""
    hot_topic_sources: str = ""
    topic_article_max_chars: int = Field(default=4000, ge=500, le=20000)
    memecub_enabled: bool = False
    memecub_api_key: str = ""
    memecub_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    deep_research_enabled: bool = False
    deep_research_max_steps: int = Field(default=5, ge=1, le=30)
    deep_research_timeout_seconds: float = Field(default=25.0, gt=0)
    deep_research_max_tokens: int = Field(default=20_000, ge=1000)
    # Hard timeout for the research extraction LLM call(s).
    research_llm_timeout_seconds: float = Field(default=15.0, gt=0)
    deep_revision_enabled: bool = True
    deep_revision_max_steps: int = Field(default=6, ge=1, le=30)
    deep_revision_timeout_seconds: float = Field(default=90.0, gt=0)
    deep_revision_max_tokens: int = Field(default=20_000, ge=1000)

    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    langfuse_enabled: bool = False
    langfuse_host: str = "http://127.0.0.1:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @property
    def langfuse_configured(self) -> bool:
        return bool(
            self.langfuse_enabled
            and self.langfuse_host.strip()
            and self.langfuse_public_key.strip()
            and self.langfuse_secret_key.strip()
        )

    @field_validator("data_dir", "skills_dir", "prompts_dir", "log_dir", mode="before")
    @classmethod
    def _resolve_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @field_validator("database_url", "checkpoint_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def effective_checkpoint_url(self) -> str:
        if self.checkpoint_url:
            return self.checkpoint_url
        return f"sqlite:///{(self.data_dir / 'checkpoints.sqlite').as_posix()}"

    @property
    def feed_urls(self) -> list[str]:
        return [item.strip() for item in self.hot_topics_feeds.split(",") if item.strip()]

    @property
    def hot_source_specs(self) -> list[HotSourceSpec]:
        return parse_hot_source_specs(self.hot_topic_sources, self.feed_urls)

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.log_dir, (self.data_dir / "backups")):
            path.mkdir(parents=True, exist_ok=True)

    @model_validator(mode="after")
    def _validate_secret(self) -> "Settings":
        if self.secret_key is not None and len(self.secret_key) < 8:
            raise ValueError("secret_key must be at least 8 characters when provided")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
