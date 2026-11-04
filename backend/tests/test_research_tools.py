"""Search/fetch tools: timeout, retry, robots and truncation."""

from __future__ import annotations

import time

import httpx
import pytest

from app.article_generation.research import tools
from app.article_generation.research.search_engines import (
    build_engine_request,
    parse_engine_html,
    parse_engine_names,
)
from app.article_generation.research.search_guard import SearchGuard
from app.article_generation.research.tools import (
    HttpSearchTool,
    SearchUnavailable,
    UrlFetcher,
)

BING_RESULT_HTML = """
<li class="b_algo">
  <h2><a href="https://example.com/a">示例 A</a></h2>
  <p>摘要 A</p>
</li>
"""


class Settings:
    search_endpoint = "https://search.test/api"
    search_api_key = "secret"
    search_timeout_seconds = 3.0
    search_max_retries = 2


class FreeSettings:
    search_endpoint = None
    search_api_key = None
    search_timeout_seconds = 3.0
    search_max_retries = 1

    def __init__(self, engines: str = "duckduckgo") -> None:
        self.search_engines = engines


def _html_response(html: str, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=html,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", url),
    )


def test_search_parses_results_and_sends_auth(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "标题", "url": "https://a.test/x", "snippet": "摘要"},
                    {"url": "https://b.test/y"},
                    {"title": "无链接"},
                ]
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    results = HttpSearchTool(Settings()).search("查询", limit=3)
    assert [item.url for item in results] == ["https://a.test/x", "https://b.test/y"]
    assert results[1].title == "https://b.test/y"
    assert calls[0]["params"] == {"q": "查询", "limit": 3}
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["timeout"] == 3.0


def test_search_retries_server_errors_then_succeeds(monkeypatch):
    statuses = [500, 503, 200]

    def fake_get(url, **kwargs):
        status = statuses.pop(0)
        if status == 200:
            return httpx.Response(
                200, json={"results": []}, request=httpx.Request("GET", url)
            )
        return httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    assert HttpSearchTool(Settings()).search("q") == []
    assert statuses == []


def test_search_timeout_exhausts_retries(monkeypatch):
    attempts = 0

    def fake_get(url, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=httpx.Request("GET", url))

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    with pytest.raises(SearchUnavailable):
        HttpSearchTool(Settings()).search("q")
    assert attempts == 3


def test_search_without_any_provider_raises():
    class NoProvider:
        search_endpoint = None
        search_api_key = None
        search_engines = ""
        search_timeout_seconds = 3.0
        search_max_retries = 0

    with pytest.raises(SearchUnavailable, match="APP_SEARCH_ENGINES"):
        HttpSearchTool(NoProvider()).search("q")


def test_free_engine_search_parses_duckduckgo(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _html_response(
            """
            <div class="result results_links">
              <h2 class="result__title">
                <a class="result__a"
                   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs%3Fx%3D1">官方文档</a>
              </h2>
              <a class="result__snippet">API 说明 <b>摘要</b></a>
            </div>
            <div class="result result--ad">
              <a class="result__a" href="https://ads.test/">广告</a>
            </div>
            """,
            url,
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    results = HttpSearchTool(FreeSettings("duckduckgo")).search("Python 教程", limit=3)

    assert [item.url for item in results] == ["https://example.com/docs?x=1"]
    assert results[0].title == "官方文档"
    assert results[0].snippet == "API 说明 摘要"
    assert calls[0]["url"] == "https://html.duckduckgo.com/html/"
    assert calls[0]["params"] == {"q": "Python 教程"}
    assert calls[0]["follow_redirects"] is True


def test_free_engines_fall_through_in_configured_order(monkeypatch):
    attempted: list[str] = []

    def fake_get(url, **kwargs):
        attempted.append(url)
        if "duckduckgo" in url:
            return httpx.Response(503, request=httpx.Request("GET", url))
        return _html_response(
            """
            <div class="result c-container">
              <h3 class="t"><a href="/link?url=baidu-result">百度结果</a></h3>
              <div class="c-abstract">百度摘要</div>
            </div>
            """,
            url,
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    results = HttpSearchTool(FreeSettings("duckduckgo,baidu")).search("AI", limit=5)

    assert [item.url for item in results] == ["https://www.baidu.com/link?url=baidu-result"]
    assert "duckduckgo" in attempted[0]
    assert "baidu.com" in attempted[-1]


def test_wall_clock_budget_stops_after_slow_engine(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        time.sleep(0.12)
        return _html_response("<html>无结果</html>", url)

    class SlowSettings(FreeSettings):
        search_timeout_seconds = 0.05
        search_max_retries = 0
        search_budget_seconds = 0.05

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    started = time.monotonic()
    with pytest.raises(SearchUnavailable, match="预算"):
        HttpSearchTool(SlowSettings("bing,360"), guard=SearchGuard(min_interval_seconds=0)).search(
            "AI", limit=5
        )
    elapsed = time.monotonic() - started
    assert len(calls) == 1
    assert elapsed < 1.0


def test_free_engines_all_failing_raises(monkeypatch):
    monkeypatch.setattr(
        tools.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(503, request=httpx.Request("GET", url)),
    )
    with pytest.raises(SearchUnavailable, match="所有搜索来源均失败"):
        HttpSearchTool(FreeSettings("duckduckgo,google")).search("q")


def test_parse_google_unwraps_redirect_and_skips_duplicates():
    html = """
    <div class="g">
      <a href="/url?q=https://example.com/a&amp;sa=U"><h3>结果 A</h3></a>
      <div class="VwiC3b">摘要 A</div>
    </div>
    <div class="g">
      <a href="/url?q=https://example.com/a&amp;sa=U"><h3>重复 A</h3></a>
    </div>
    <div class="g">
      <a href="https://example.com/b"><h3>结果 B</h3></a>
    </div>
    """
    results = parse_engine_html("google", html, 5)
    assert [item.url for item in results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert results[0].snippet == "摘要 A"


def test_parse_engine_names_ignores_unknown_and_aliases():
    assert parse_engine_names("ddg, bing, Google, baidu, so, weixin, sogou") == [
        "duckduckgo",
        "bing",
        "google",
        "baidu",
        "360",
        "wechat",
    ]
    assert parse_engine_names("") == []


def test_parse_bing_uses_direct_links_and_snippets():
    html = """
    <li class="b_algo">
      <h2><a href="https://www.runoob.com/python3/python-asyncio.html">菜鸟教程</a></h2>
      <div class="b_caption"><p class="b_lineclamp2">asyncio 标准库说明</p></div>
    </li>
    <li class="b_algo">
      <h2><a href="https://cn.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9i">示例 B</a></h2>
      <p>摘要 B</p>
    </li>
    """
    results = parse_engine_html("bing", html, 5)
    assert [item.url for item in results] == [
        "https://www.runoob.com/python3/python-asyncio.html",
        "https://example.com/b",
    ]
    assert results[0].snippet == "asyncio 标准库说明"


def test_parse_360_prefers_data_mdurl_and_filters_internal_links():
    html = """
    <li class="res-list">
      <h3><a href="https://www.so.com/link?m=abc"
             data-mdurl="https://blog.csdn.net/a/1">CSDN 文章</a></h3>
      <p class="res-desc">360 摘要</p>
    </li>
    <li class="res-list">
      <h3><a href="https://tv.360kan.com/s?q=x">短视频</a></h3>
    </li>
    <li class="res-list">
      <h3><a href="https://www.so.com/s?q=more">更多结果</a></h3>
    </li>
    """
    results = parse_engine_html("360", html, 5)
    assert [item.url for item in results] == ["https://blog.csdn.net/a/1"]
    assert results[0].snippet == "360 摘要"


def test_build_engine_request_supports_bing_and_360():
    bing = build_engine_request("bing", "查询", 8)
    assert bing.url == "https://cn.bing.com/search"
    assert bing.params["q"] == "查询"

    so = build_engine_request("360", "查询", 8)
    assert so.url == "https://www.so.com/s"
    assert so.params["q"] == "查询"

    wechat = build_engine_request("wechat", "查询", 8)
    assert wechat.url == "https://weixin.sogou.com/weixin"
    assert wechat.params["type"] == 2


WECHAT_LIST_HTML = """
<ul class="news-list">
  <li>
    <h3><a href="/link?url=abc">公众号文章标题</a></h3>
    <p class="txt-info">文章摘要内容</p>
    <div class="s-p">
      <span class="all-time-y2">某公众号</span>
      <span class="s2"><script>document.write(timeConvert('1700000000'))</script></span>
    </div>
  </li>
</ul>
"""


def test_parse_wechat_articles():
    results = parse_engine_html("wechat", WECHAT_LIST_HTML, 5)
    assert results[0].url == "https://weixin.sogou.com/link?url=abc"
    assert results[0].title == "公众号文章标题"
    assert results[0].snippet == "文章摘要内容"
    assert results[0].published_at == "2023-11-14T22:13:20+00:00"


def test_wechat_engine_resolves_mp_weixin_url(monkeypatch):
    redirect_html = (
        "<script>var url = '';"
        "url += 'https://mp.';"
        "url += 'weixin.qq.com/s?src=11';</script>"
    )

    def fake_get(url, **kwargs):
        if "weixin.sogou.com/weixin" in url:
            return _html_response(WECHAT_LIST_HTML, url)
        return _html_response(redirect_html, url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    results = HttpSearchTool(FreeSettings("wechat")).search("AI", limit=3)
    assert [item.url for item in results] == ["https://mp.weixin.qq.com/s?src=11"]


def test_build_engine_request_uses_free_endpoints():
    request = build_engine_request("baidu", "查询", 8)
    assert request.url == "https://www.baidu.com/s"
    assert request.params["wd"] == "查询"
    assert request.headers["User-Agent"].startswith("Mozilla/5.0")


def test_cooling_engine_is_skipped(monkeypatch):
    attempted: list[str] = []

    def fake_get(url, **kwargs):
        attempted.append(url)
        return _html_response(BING_RESULT_HTML, url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    guard = SearchGuard(cooldown_seconds=60, min_interval_seconds=0)
    guard.record_failure("duckduckgo")

    results = HttpSearchTool(
        FreeSettings("duckduckgo,bing"), guard=guard
    ).search("AI", limit=3)

    assert [item.url for item in results] == ["https://example.com/a"]
    assert len(attempted) == 1
    assert "bing.com" in attempted[0]


def test_repeated_query_hits_cache_without_new_request(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _html_response(BING_RESULT_HTML, url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    guard = SearchGuard(min_interval_seconds=0)
    tool = HttpSearchTool(FreeSettings("bing"), guard=guard)

    first = tool.search("AI Agent", limit=3)
    second = tool.search("AI Agent", limit=3)

    assert len(calls) == 1
    assert [item.url for item in second] == [item.url for item in first]


def test_expired_cache_requests_again(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _html_response(BING_RESULT_HTML, url)

    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    clock = Clock()
    guard = SearchGuard(
        min_interval_seconds=0,
        cache_ttl_seconds=10,
        clock=clock,
        sleep=clock.sleep,
    )
    tool = HttpSearchTool(FreeSettings("bing"), guard=guard)

    tool.search("AI", limit=3)
    tool.search("AI", limit=3)
    assert len(calls) == 1

    clock.now = 11.0
    tool.search("AI", limit=3)
    assert len(calls) == 2


def test_request_budget_returns_collected_results(monkeypatch):
    attempted: list[str] = []

    def fake_get(url, **kwargs):
        attempted.append(url)
        return _html_response(BING_RESULT_HTML, url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    guard = SearchGuard(min_interval_seconds=0, max_requests_per_call=1)
    results = HttpSearchTool(
        FreeSettings("bing,360"), guard=guard
    ).search("AI", limit=5)

    assert [item.url for item in results] == ["https://example.com/a"]
    assert len(attempted) == 1


def test_request_budget_exhausted_without_results_raises(monkeypatch):
    attempted: list[str] = []

    def fake_get(url, **kwargs):
        attempted.append(url)
        return _html_response("<html>无结果</html>", url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    guard = SearchGuard(min_interval_seconds=0, max_requests_per_call=1)

    with pytest.raises(SearchUnavailable, match="预算"):
        HttpSearchTool(FreeSettings("bing,360"), guard=guard).search("AI", limit=5)
    assert len(attempted) == 1


def test_disabled_guard_skips_throttle_and_cache(monkeypatch):
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _html_response(BING_RESULT_HTML, url)

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    guard = SearchGuard(
        enabled=False,
        min_interval_seconds=10,
        cache_ttl_seconds=600,
        sleep=sleeps.append,
    )
    tool = HttpSearchTool(FreeSettings("bing"), guard=guard)

    tool.search("AI", limit=3)
    tool.search("AI", limit=3)

    assert len(calls) == 2
    assert sleeps == []


def test_fetch_respects_robots(monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /private\n",
                request=httpx.Request("GET", url),
            )
        raise AssertionError("robots 拒绝后不应请求正文")

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    with pytest.raises(PermissionError):
        UrlFetcher().fetch("https://x.test/private/page")


def test_fetch_truncates_long_text(monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text="a" * 500,
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    assert UrlFetcher(max_bytes=100).fetch("https://x.test/page") == "a" * 100


def test_fetch_sends_identifiable_user_agent(monkeypatch):
    seen: dict[str, str] = {}

    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=httpx.Request("GET", url))
        seen.update(kwargs.get("headers") or {})
        return httpx.Response(
            200,
            text="<html>ok</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    assert UrlFetcher().fetch("https://x.test/page") == "<html>ok</html>"
    assert seen.get("User-Agent", "").startswith("ArticleAutopilot/")


def test_fetch_rejects_binary_content(monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            content=b"\x00\x01",
            headers={"content-type": "application/octet-stream"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tools.httpx, "get", fake_get)
    with pytest.raises(ValueError, match="内容类型"):
        UrlFetcher().fetch("https://x.test/file")
