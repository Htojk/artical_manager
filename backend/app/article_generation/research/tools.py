"""Search and URL fetching tools used by the research stage.

Search is deliberately implemented as plain functional code: free HTML search
engines (DuckDuckGo, Baidu, Google) are called over ordinary HTTP and parsed
locally.  A user-configured JSON search endpoint remains optional and, when
present, is tried first.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

import httpx

from app.article_generation.research.search_engines import (
    BROWSER_USER_AGENT,
    SearchEngineError,
    SearchResult,
    build_engine_request,
    parse_engine_html,
    parse_engine_names,
)
from app.article_generation.research.search_guard import (
    SearchGuard,
    get_search_guard,
)
from app.core.config import Settings, get_settings
from app.core.tracing import trace_span
from app.core.web import UrlFetcher

__all__ = [
    "HttpSearchTool",
    "SearchEngineError",
    "SearchResult",
    "SearchUnavailable",
    "UrlFetcher",
]

logger = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    pass


_WECHAT_URL_JS = re.compile(r"url\s*\+?=\s*'([^']*)'")


class HttpSearchTool:
    """Searches the web via free engines, optionally falling back to a JSON API."""

    def __init__(
        self,
        settings: Settings | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        guard: SearchGuard | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout if timeout is not None else self.settings.search_timeout_seconds
        self.retries = retries if retries is not None else self.settings.search_max_retries
        self.engine_names = parse_engine_names(
            getattr(self.settings, "search_engines", "")
        )
        self.budget = float(getattr(self.settings, "search_budget_seconds", 12.0))
        self.guard = guard or get_search_guard(self.settings)

    # ------------------------------------------------------------------ HTTP

    def _request(
        self,
        endpoint: str,
        params: dict,
        headers: dict,
        *,
        deadline: float | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            timeout = self.timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SearchUnavailable("搜索总耗时预算已用尽")
                timeout = min(timeout, remaining)
            try:
                response = httpx.get(
                    endpoint,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                )
                if response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"search service returned {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                logger.warning(
                    "search request failed (attempt %s/%s): %s",
                    attempt + 1,
                    self.retries + 1,
                    exc,
                )
        raise SearchUnavailable(f"搜索服务请求失败: {last_error}") from last_error

    # ------------------------------------------------------------- providers

    def _search_endpoint(
        self, query: str, limit: int, *, deadline: float | None = None
    ) -> list[SearchResult]:
        endpoint = self.settings.search_endpoint
        if not endpoint:
            return []
        headers: dict[str, str] = {}
        if self.settings.search_api_key:
            headers["Authorization"] = f"Bearer {self.settings.search_api_key}"
        response = self._request(
            endpoint, {"q": query, "limit": limit}, headers, deadline=deadline
        )
        payload = response.json()
        items = payload.get("results") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise SearchUnavailable("搜索服务返回格式无效")
        results: list[SearchResult] = []
        for item in items[:limit]:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or item["url"]),
                    url=str(item["url"]),
                    snippet=str(item.get("snippet") or item.get("content") or ""),
                    published_at=item.get("published_at"),
                )
            )
        return results

    def _search_engine(
        self,
        engine: str,
        query: str,
        limit: int,
        *,
        deadline: float | None = None,
    ) -> list[SearchResult]:
        request = build_engine_request(engine, query, limit)
        response = self._request(
            request.url, request.params, request.headers, deadline=deadline
        )
        results = parse_engine_html(engine, response.text, limit)
        if engine == "baidu":
            results = self._resolve_baidu_redirects(results, deadline=deadline)
        elif engine == "wechat":
            # Sogou signs link pages against the SNUID/SUID cookies set by the
            # search response, so carry them into every redirect request.
            results = self._resolve_wechat_redirects(
                results, cookies=response.cookies, deadline=deadline
            )
        return results

    def _resolve_baidu_redirects(
        self, results: list[SearchResult], *, deadline: float | None = None
    ) -> list[SearchResult]:
        """Turn Baidu redirect links into the real article URLs, best effort."""
        resolved: list[SearchResult] = []
        seen: set[str] = set()
        for item in results:
            parsed = urlparse(item.url)
            if parsed.netloc.endswith("baidu.com") and parsed.path.startswith("/link"):
                timeout = self._redirect_timeout(deadline)
                if timeout is not None:
                    try:
                        response = httpx.get(
                            item.url,
                            headers={"User-Agent": BROWSER_USER_AGENT},
                            timeout=timeout,
                            follow_redirects=True,
                        )
                        if response.status_code < 400:
                            item.url = str(response.url)
                    except httpx.HTTPError as exc:
                        logger.debug("failed to resolve baidu redirect %s: %s", item.url, exc)
            final = urlparse(item.url)
            if final.netloc in {"www.baidu.com", "m.baidu.com"} and not final.path.startswith(
                "/link"
            ):
                continue
            if item.url in seen:
                continue
            seen.add(item.url)
            resolved.append(item)
        return resolved

    def _redirect_timeout(self, deadline: float | None) -> float | None:
        timeout = min(self.timeout, 10.0)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            timeout = min(timeout, remaining)
        return timeout

    def _resolve_wechat_redirects(
        self,
        results: list[SearchResult],
        *,
        cookies: httpx.Cookies | None = None,
        deadline: float | None = None,
    ) -> list[SearchResult]:
        """Reconstruct the mp.weixin.qq.com URL hidden in Sogou's JS redirect."""
        resolved: list[SearchResult] = []
        seen: set[str] = set()
        headers = {
            "User-Agent": BROWSER_USER_AGENT,
            "Referer": "https://weixin.sogou.com/",
        }
        for item in results:
            parsed = urlparse(item.url)
            if parsed.netloc.endswith("weixin.sogou.com") and parsed.path.startswith("/link"):
                timeout = self._redirect_timeout(deadline)
                if timeout is not None:
                    try:
                        response = httpx.get(
                            item.url,
                            headers=headers,
                            cookies=cookies,
                            timeout=timeout,
                            follow_redirects=True,
                        )
                        target = "".join(_WECHAT_URL_JS.findall(response.text)).replace("@", "")
                        if target.startswith("https://mp.weixin.qq.com/"):
                            item.url = target
                    except httpx.HTTPError as exc:
                        logger.debug("failed to resolve wechat link %s: %s", item.url, exc)
            if item.url in seen:
                continue
            seen.add(item.url)
            resolved.append(item)
        return resolved

    def _dispatch(self, query: str, limit: int) -> tuple[list[SearchResult], list[str]]:
        errors: list[str] = []
        deadline = time.monotonic() + self.budget

        # Optional user-configured JSON endpoint is tried first and wins outright.
        if self.settings.search_endpoint:
            try:
                custom = self._search_endpoint(query, limit, deadline=deadline)
            except Exception as exc:  # noqa: BLE001 - fall back to free engines
                errors.append(f"自定义搜索服务: {exc}")
                logger.warning("custom search endpoint failed: %s", exc)
            else:
                return custom[:limit], ["endpoint"]

        if not self.engine_names:
            detail = "; ".join(errors) if errors else ""
            if detail:
                raise SearchUnavailable(f"搜索失败: {detail}")
            raise SearchUnavailable(
                "未配置搜索来源（APP_SEARCH_ENGINES 或 APP_SEARCH_ENDPOINT）"
            )

        collected: list[SearchResult] = []
        seen: set[str] = set()
        used: list[str] = []
        requests_made = 0
        budget = self.guard.max_requests_per_call if self.guard.enabled else None

        for engine in self.engine_names:
            if len(collected) >= limit:
                break
            if time.monotonic() >= deadline:
                errors.append(f"搜索总耗时预算已用尽({self.budget}s)")
                logger.info("search wall-clock budget exhausted")
                break
            # Slight over-fetch so internal/ad results filtered by the parser
            # do not leave us short of the requested limit.
            request_limit = min(limit - len(collected) + 2, 20)
            cached = self.guard.get_cached(engine, query, request_limit)
            if cached is None:
                if budget is not None and requests_made >= budget:
                    errors.append(f"搜索请求预算已用尽({budget})")
                    logger.info(
                        "search request budget exhausted after %s request(s)",
                        requests_made,
                    )
                    break
                if not self.guard.acquire(engine):
                    errors.append(f"{engine}: 冷却中")
                    logger.debug("skipping search engine %s (cooling down)", engine)
                    continue
                requests_made += 1
                try:
                    items = self._search_engine(
                        engine, query, request_limit, deadline=deadline
                    )
                except Exception as exc:  # noqa: BLE001 - try the next engine
                    errors.append(f"{engine}: {exc}")
                    self.guard.record_failure(engine)
                    logger.warning("search engine %s failed: %s", engine, exc)
                    continue
                self.guard.record_success(engine, query, request_limit, items)
            else:
                items = cached
                logger.debug("search cache hit for %s: %s", engine, query)
            added = 0
            for item in items:
                if item.url in seen:
                    continue
                seen.add(item.url)
                collected.append(item)
                added += 1
                if len(collected) >= limit:
                    break
            if added:
                used.append(engine)

        if not collected:
            raise SearchUnavailable("所有搜索来源均失败: " + "; ".join(errors))
        return collected, used

    # ----------------------------------------------------------------- public

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        with trace_span(
            "search.query", input={"query": query, "limit": limit}
        ) as span:
            try:
                results, engines = self._dispatch(query, limit)
            except Exception as exc:
                if span is not None:
                    span.update(
                        output={"status": "error", "error": str(exc)},
                        level="ERROR",
                        status_message=str(exc),
                    )
                raise
            if span is not None:
                span.update(
                    output={"status": "ok", "count": len(results), "engines": engines}
                )
            return results
