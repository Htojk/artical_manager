"""On-demand, read-only checks for the external services used by the app."""

from __future__ import annotations

import logging
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.article_generation.research.search_engines import (
    build_engine_request,
    parse_engine_html,
    parse_engine_names,
)
from app.article_generation.topic_selection.sources.html import parse_html_list
from app.article_generation.topic_selection.sources.rss import parse_feed
from app.core.config import HotSourceSpec, Settings

logger = logging.getLogger(__name__)
logger_httpx = logging.getLogger("httpx")
logger_httpx.setLevel(logging.WARNING)  # WeChat's token request includes a secret in its URL.

REPORT_SETTING_KEY = "external_connectivity_latest"
PROBE_QUERY = "人工智能"


class ProbeFailure(Exception):
    """Expected failure whose message is safe to show in the UI."""


def _host(url: str) -> str:
    return urlparse(url).hostname or "未设置地址"


class ConnectivityChecker:
    def __init__(
        self,
        settings: Settings,
        wechat_credentials: dict | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.wechat_credentials = wechat_credentials or {}
        self.transport = transport

    def _client(self, timeout: float = 8.0) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=timeout, follow_redirects=True)

    @staticmethod
    def _response(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise ProbeFailure(f"HTTP {response.status_code}")

    def _feed(self, spec: HotSourceSpec) -> str:
        with self._client() as client:
            response = client.get(spec.url, headers={"User-Agent": "ArticleAutopilot/0.1 (+local)"})
        self._response(response)
        try:
            if spec.kind == "html":
                items = parse_html_list(response.text, spec, limit=20)
            else:
                items = parse_feed(response.text, spec.url, source_name=spec.name)[:20]
        except (ValueError, SyntaxError) as exc:
            raise ProbeFailure("返回内容无法按配置解析") from exc
        usable = sum(bool(item.title and item.url) for item in items)
        if not usable:
            raise ProbeFailure("页面可访问，但未解析到带链接的条目")
        return f"可解析 {usable} 条"

    def _search_engine(self, engine: str) -> str:
        request = build_engine_request(engine, PROBE_QUERY, 3)
        with self._client(timeout=self.settings.search_timeout_seconds) as client:
            response = client.get(request.url, params=request.params, headers=request.headers)
        self._response(response)
        results = parse_engine_html(engine, response.text, 3)
        if not results:
            raise ProbeFailure("页面可访问，但未解析到搜索结果（可能是验证码或页面变化）")
        return f"可解析 {len(results)} 条结果"

    def _search_endpoint(self) -> str:
        headers = {}
        if self.settings.search_api_key:
            headers["Authorization"] = f"Bearer {self.settings.search_api_key}"
        with self._client(timeout=self.settings.search_timeout_seconds) as client:
            response = client.get(
                self.settings.search_endpoint,
                params={"q": PROBE_QUERY, "limit": 3},
                headers=headers,
            )
        self._response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProbeFailure("返回内容不是 JSON") from exc
        rows = data.get("results") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ProbeFailure("返回格式缺少 results 列表")
        if not any(isinstance(row, dict) and row.get("url") for row in rows):
            raise ProbeFailure("接口可访问，但没有可用搜索结果")
        return f"可用结果 {len(rows)} 条"

    def _memecub(self) -> str:
        with self._client(timeout=self.settings.memecub_timeout_seconds) as client:
            response = client.get(
                "https://memecub.com/api/v1/search",
                params={"q": "无语", "limit": 1, "commercial": 1},
                headers={"Authorization": f"Bearer {self.settings.memecub_api_key}"},
            )
        self._response(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProbeFailure("返回内容不是 JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ProbeFailure("返回格式缺少 data 列表")
        return f"接口正常，可商用结果 {len(data['data'])} 条"

    def _wechat(self) -> str:
        credentials = self.wechat_credentials
        with self._client(timeout=10) as client:
            response = client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={"grant_type": "client_credential", "appid": credentials["app_id"],
                        "secret": credentials["app_secret"]},
            )
            self._response(response)
            token_data = response.json()
            token = token_data.get("access_token") if isinstance(token_data, dict) else None
            if not token:
                code = token_data.get("errcode") if isinstance(token_data, dict) else None
                raise ProbeFailure(f"获取令牌失败（错误码 {code or '未知'}）")
            response = client.get(
                "https://api.weixin.qq.com/cgi-bin/draft/count",
                params={"access_token": token},
            )
        self._response(response)
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("total_count"), int):
            code = data.get("errcode") if isinstance(data, dict) else None
            raise ProbeFailure(f"草稿接口不可用（错误码 {code or '未知'}）")
        return "令牌与草稿接口可用"

    def _llm(self) -> str:
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        with self._client(timeout=min(self.settings.llm_timeout_seconds, 15.0)) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={"model": self.settings.llm_model,
                      "messages": [{"role": "user", "content": "只回复 OK"}],
                      "max_tokens": 5},
            )
        self._response(response)
        data = response.json()
        if not isinstance(data, dict) or not data.get("choices"):
            raise ProbeFailure("模型接口未返回回复")
        return "模型可回复"

    @staticmethod
    def _run_one(key: str, group: str, name: str, target: str, action) -> dict:
        started = time.monotonic()
        try:
            message = action()
            status = "ok"
        except ProbeFailure as exc:
            status, message = "failed", str(exc)
        except httpx.TimeoutException:
            status, message = "failed", "连接超时"
        except httpx.ConnectError:
            status, message = "failed", "无法建立连接"
        except Exception as exc:  # noqa: BLE001 - never expose URLs or credentials from exceptions
            logger.warning("connectivity probe %s failed: %s", key, type(exc).__name__)
            status, message = "failed", f"检测异常（{type(exc).__name__}）"
        return {
            "key": key, "group": group, "name": name, "target": target,
            "status": status, "message": message,
            "latency_ms": round((time.monotonic() - started) * 1000),
        }

    @staticmethod
    def _skipped(key: str, group: str, name: str, target: str, message: str) -> dict:
        return {"key": key, "group": group, "name": name, "target": target,
                "status": "skipped", "message": message, "latency_ms": 0}

    def run(self) -> dict:
        probes = []
        configuration_items = []
        if self.settings.hot_topic_sources.strip():
            try:
                configured_sources = json.loads(self.settings.hot_topic_sources)
            except json.JSONDecodeError:
                configured_sources = None
            if not isinstance(configured_sources, list) or not configured_sources:
                configuration_items.append({
                    "key": "feed:configuration", "group": "feed", "name": "热点信源配置",
                    "target": "", "status": "failed",
                    "message": "APP_HOT_TOPIC_SOURCES 不是非空 JSON 数组；当前使用回退信源",
                    "latency_ms": 0,
                })
            else:
                for index, entry in enumerate(configured_sources):
                    valid = (isinstance(entry, dict)
                             and isinstance(entry.get("url"), str)
                             and entry["url"].startswith(("https://", "http://"))
                             and str(entry.get("type") or "rss").strip().lower() in {"rss", "html"})
                    if not valid:
                        configuration_items.append({
                            "key": f"feed:invalid:{index}", "group": "feed",
                            "name": f"信源配置第 {index + 1} 项", "target": "",
                            "status": "failed", "message": "URL 或类型无效，已被忽略",
                            "latency_ms": 0,
                        })
        for index, spec in enumerate(self.settings.hot_source_specs):
            probes.append((f"feed:{index}", "feed", spec.name, _host(spec.url),
                           lambda spec=spec: self._feed(spec)))
        engines = parse_engine_names(self.settings.search_engines)
        for engine in engines:
            request = build_engine_request(engine, PROBE_QUERY, 3)
            probes.append((f"search:{engine}", "search", engine, _host(request.url),
                           lambda engine=engine: self._search_engine(engine)))
        if self.settings.search_endpoint:
            probes.append(("search:endpoint", "search", "自定义搜索接口",
                           _host(self.settings.search_endpoint), self._search_endpoint))
        if self.settings.memecub_enabled and self.settings.memecub_api_key:
            probes.append(("memecub", "media", "Memecub", "memecub.com", self._memecub))
        if self.settings.llm_api_key:
            probes.append(("llm:default", "model", "默认模型接口",
                           _host(self.settings.llm_base_url), self._llm))
        if self.wechat_credentials.get("app_id") and self.wechat_credentials.get("app_secret"):
            probes.append(("wechat", "platform", "微信公众号草稿",
                           "api.weixin.qq.com", self._wechat))

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(self._run_one, *probe) for probe in probes]
            items = configuration_items + [future.result() for future in futures]
        for name in dict.fromkeys(part.strip() for part in self.settings.search_engines.split(",") if part.strip()):
            if not parse_engine_names(name):
                items.append({"key": f"search:unsupported:{name}", "group": "search",
                              "name": name, "target": "", "status": "failed",
                              "message": "不支持的搜索引擎配置", "latency_ms": 0})
        if not engines:
            items.append(self._skipped("search:free", "search", "免费搜索引擎", "", "未配置"))
        if not self.settings.search_endpoint:
            items.append(self._skipped("search:endpoint", "search", "自定义搜索接口", "", "未配置（可选）"))
        if not self.settings.memecub_enabled:
            items.append(self._skipped("memecub", "media", "Memecub", "memecub.com", "未启用"))
        elif not self.settings.memecub_api_key:
            items.append(self._skipped("memecub", "media", "Memecub", "memecub.com", "缺少 API Key"))
        if not self.settings.llm_api_key:
            items.append(self._skipped("llm:default", "model", "默认模型接口", _host(self.settings.llm_base_url), "缺少 API Key"))
        if not (self.wechat_credentials.get("app_id") and self.wechat_credentials.get("app_secret")):
            items.append(self._skipped("wechat", "platform", "微信公众号草稿", "api.weixin.qq.com", "未配置凭据"))
        summary = {status: sum(item["status"] == status for item in items)
                   for status in ("ok", "failed", "skipped")}
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "status": "degraded" if summary["failed"] else "ok",
            "summary": summary,
            "items": items,
        }
