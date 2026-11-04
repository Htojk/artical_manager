"""External connectivity checks use real parsers without network access."""

from __future__ import annotations

import json

import httpx

from app.core.config import HotSourceSpec
from app.monitoring.connectivity import ConnectivityChecker


def test_connectivity_checks_and_redacts_secrets(test_settings, monkeypatch):
    monkeypatch.setattr(
        type(test_settings), "hot_source_specs",
        property(lambda _: [HotSourceSpec("测试 RSS", "rss", "https://feed.example/rss")]),
    )
    test_settings.search_engines = "bing"
    test_settings.search_endpoint = "https://search.example/api"
    test_settings.search_api_key = "private-search-key"
    test_settings.memecub_enabled = True
    test_settings.memecub_api_key = "private-meme-key"
    test_settings.llm_base_url = "https://model.example/v1"
    test_settings.llm_api_key = "private-model-key"

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "feed.example":
            return httpx.Response(200, text="<rss><channel><item><title>AI 新闻</title><link>https://example.com/news</link></item></channel></rss>")
        if host == "search.example":
            return httpx.Response(200, json={"results": [{"title": "结果", "url": "https://example.com"}]})
        if host == "memecub.com":
            return httpx.Response(200, json={"data": []})
        if host == "model.example":
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        if host == "api.weixin.qq.com":
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "private-access-token"})
            return httpx.Response(200, json={"total_count": 0})
        return httpx.Response(200, text="<html>captcha</html>")

    report = ConnectivityChecker(
        test_settings,
        {"app_id": "public-id", "app_secret": "private-wechat-secret"},
        transport=httpx.MockTransport(handler),
    ).run()
    by_key = {item["key"]: item for item in report["items"]}
    assert report["summary"] == {"ok": 5, "failed": 1, "skipped": 0}
    assert by_key["search:bing"]["status"] == "failed"
    assert "验证码" in by_key["search:bing"]["message"]
    assert by_key["feed:0"]["status"] == "ok"
    assert by_key["wechat"]["status"] == "ok"
    serialized = json.dumps(report)
    for secret in ("private-search-key", "private-meme-key", "private-model-key", "private-wechat-secret", "private-access-token"):
        assert secret not in serialized


def test_connectivity_api_persists_latest_report(client_env, monkeypatch):
    report = {
        "checked_at": "2026-11-04T00:00:00+00:00",
        "status": "degraded",
        "summary": {"ok": 0, "failed": 1, "skipped": 0},
        "items": [{"key": "feed:0", "group": "feed", "name": "测试", "target": "example.com", "status": "failed", "message": "HTTP 503", "latency_ms": 12}],
    }
    monkeypatch.setattr(ConnectivityChecker, "run", lambda self: report)
    assert client_env.client.get("/api/health/connectivity").json()["status"] == "not_checked"
    response = client_env.client.post("/api/health/connectivity/check")
    assert response.status_code == 200
    assert response.json() == report
    assert client_env.client.get("/api/health/connectivity").json() == report


def test_bad_source_configuration_is_visible(test_settings, monkeypatch):
    test_settings.hot_topic_sources = '[{"name":"坏信源","url":"ftp://invalid"}]'
    test_settings.search_engines = "unknown"
    test_settings.llm_api_key = ""
    monkeypatch.setattr(
        type(test_settings), "hot_source_specs", property(lambda _: []),
    )
    report = ConnectivityChecker(test_settings).run()
    failures = {item["key"]: item for item in report["items"] if item["status"] == "failed"}
    assert "feed:invalid:0" in failures
    assert "search:unsupported:unknown" in failures
