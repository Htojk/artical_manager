"""Hot-topic source parsing: RSS/Atom, HTML list pages and the collector."""

from __future__ import annotations

import httpx

from app.article_generation.topic_selection.sources import collector
from app.article_generation.topic_selection.sources.collector import HotTopicSource
from app.article_generation.topic_selection.sources.html import parse_html_list
from app.article_generation.topic_selection.sources.rss import parse_feed
from app.core.config import HotSourceSpec

LIST_HTML = """
<html><body>
  <article class="post">
    <h2><a href="/p/1">AI 新进展：推理成本下降</a></h2>
    <time datetime="2026-10-01T08:00:00+08:00">10 月 1 日</time>
  </article>
  <article class="post">
    <h2><a href="javascript:void(0)">广告位</a></h2>
  </article>
  <article class="post">
    <h2><a href="https://other.example/p/2">第二条：开源模型对比</a></h2>
  </article>
</body></html>
"""

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>示例</title>
  <item><title>RSS 标题一</title><link>https://example.com/rss/1</link>
    <pubDate>Wed, 01 Oct 2026 08:00:00 GMT</pubDate></item>
  <item><title>RSS 标题二</title><link>https://example.com/rss/2</link></item>
</channel></rss>
"""


def _html_spec(**overrides) -> HotSourceSpec:
    values = {
        "name": "示例列表",
        "kind": "html",
        "url": "https://example.com/news",
        "item_selector": "article.post",
        "title_selector": "h2 a",
    }
    values.update(overrides)
    return HotSourceSpec(**values)


def test_parse_html_list_extracts_title_link_and_time():
    signals = parse_html_list(LIST_HTML, _html_spec())
    assert [signal.title for signal in signals] == [
        "AI 新进展：推理成本下降",
        "第二条：开源模型对比",
    ]
    assert signals[0].url == "https://example.com/p/1"
    assert signals[1].url == "https://other.example/p/2"
    assert signals[0].published_at == "2026-10-01T08:00:00+08:00"
    assert signals[0].source == "示例列表"


def test_parse_html_list_returns_empty_when_selector_does_not_match():
    assert parse_html_list(LIST_HTML, _html_spec(title_selector="h3 a")) == []


def test_parse_feed_reads_published_at():
    signals = parse_feed(RSS_XML, "https://example.com/feed", source_name="示例 RSS")
    assert [signal.title for signal in signals] == ["RSS 标题一", "RSS 标题二"]
    assert signals[0].source == "示例 RSS"
    assert signals[0].published_at == "Wed, 01 Oct 2026 08:00:00 GMT"
    assert signals[0].url == "https://example.com/rss/1"


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _install_sources(monkeypatch) -> None:
    def fake_get(url, **_kwargs):
        if "broken" in url:
            raise httpx.ConnectError("connection refused")
        if url.endswith("/news"):
            return FakeResponse(LIST_HTML)
        return FakeResponse(RSS_XML)

    monkeypatch.setattr(collector.httpx, "get", fake_get)


def test_collector_mixes_rss_and_html_and_isolates_failures(monkeypatch):
    _install_sources(monkeypatch)
    source = HotTopicSource(
        specs=[
            HotSourceSpec(name="RSS源", kind="rss", url="https://example.com/feed"),
            HotSourceSpec(
                name="列表源",
                kind="html",
                url="https://example.com/news",
                item_selector="article.post",
                title_selector="h2 a",
            ),
            HotSourceSpec(name="坏源", kind="rss", url="https://broken.example/feed"),
        ]
    )

    signals = source.fetch(limit=10)

    assert [signal.title for signal in signals] == [
        "RSS 标题一",
        "AI 新进展：推理成本下降",
        "RSS 标题二",
        "第二条：开源模型对比",
    ]
    assert [signal.index for signal in signals] == [1, 2, 3, 4]
    assert len(source.errors) == 1
    assert "坏源" in source.errors[0]


def test_collector_dedupes_titles_and_truncates(monkeypatch):
    _install_sources(monkeypatch)
    source = HotTopicSource(
        specs=[
            HotSourceSpec(name="源一", kind="rss", url="https://example.com/feed"),
            HotSourceSpec(name="源二", kind="rss", url="https://example.com/feed?dup"),
        ]
    )

    signals = source.fetch(limit=1)

    assert len(signals) == 1
    assert signals[0].index == 1
    assert signals[0].source == "源一"


def test_collector_filters_irrelevant_items_and_balances_sources(monkeypatch):
    feeds = {
        "https://one.example/feed": """<rss><channel>
            <item><title>手机新品</title><link>https://one.example/0</link>
              <description>厂商提到 AI，但主题是手机价格</description></item>
            <item><title>AI 游戏助手</title><link>https://one.example/1</link></item>
            <item><title>AI 小说实验</title><link>https://one.example/2</link></item>
        </channel></rss>""",
        "https://two.example/feed": """<rss><channel>
            <item><title>One Roof</title><link>https://two.example/0</link>
              <description>Property listings in one place</description></item>
            <item><title>Flockbay</title><link>https://two.example/1</link>
              <description>Free AI game maker</description></item>
        </channel></rss>""",
    }
    monkeypatch.setattr(
        collector.httpx, "get", lambda url, **_kwargs: FakeResponse(feeds[url])
    )
    source = HotTopicSource(specs=[
        HotSourceSpec(name="中文源", kind="rss", url="https://one.example/feed",
                      include_keywords=("AI",)),
        HotSourceSpec(name="产品源", kind="rss", url="https://two.example/feed",
                      include_keywords=("AI",), match_summary=True),
    ])

    signals = source.fetch(limit=3)

    assert [signal.title for signal in signals] == ["AI 游戏助手", "Flockbay", "AI 小说实验"]
    assert [signal.index for signal in signals] == [1, 2, 3]


def test_collector_prioritizes_account_interests_within_a_source(monkeypatch):
    feed = """<rss><channel>
        <item><title>AI 企业销售平台</title><link>https://example.com/1</link></item>
        <item><title>AI 游戏创作工具</title><link>https://example.com/2</link></item>
    </channel></rss>"""
    monkeypatch.setattr(collector.httpx, "get", lambda *_args, **_kwargs: FakeResponse(feed))
    source = HotTopicSource(specs=[HotSourceSpec(
        name="产品源", kind="rss", url="https://example.com/feed",
        include_keywords=("AI",), priority_keywords=("游戏", "创作"),
    )])

    assert [item.title for item in source.fetch(limit=2)] == [
        "AI 游戏创作工具", "AI 企业销售平台",
    ]
