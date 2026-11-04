"""Free web search engines accessed over plain HTTP, parsed locally.

No MCP server or third-party search SDK is involved: every engine is expressed
as two small pure functions -- one that builds the request, one that parses the
returned HTML -- so the research stage can search the public web directly.

Engines are best-effort HTML endpoints.  They may rate-limit, return a consent
page or change markup; the caller tries them in the configured order and falls
through to the next one.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

__all__ = [
    "DEFAULT_ENGINE_ORDER",
    "EngineRequest",
    "SearchEngineError",
    "SearchResult",
    "build_engine_request",
    "parse_engine_html",
    "parse_engine_names",
]

logger = logging.getLogger(__name__)

DEFAULT_ENGINE_ORDER = ("baidu", "bing", "360", "wechat")

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_ENGINE_ALIASES = {
    "ddg": "duckduckgo",
    "duckduckgo": "duckduckgo",
    "baidu": "baidu",
    "google": "google",
    "bing": "bing",
    "cnbing": "bing",
    "cn.bing": "bing",
    "360": "360",
    "so": "360",
    "so.com": "360",
    "wechat": "wechat",
    "weixin": "wechat",
    "sogou-wechat": "wechat",
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None


class SearchEngineError(RuntimeError):
    """A single engine request or parse failed."""


@dataclass(frozen=True)
class EngineRequest:
    url: str
    params: dict[str, Any]
    headers: dict[str, str]


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _resolve(href: str | None, home: str) -> str:
    href = (href or "").strip()
    if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
        return ""
    return urljoin(home, href)


def _unwrap_duckduckgo(href: str) -> str:
    """DuckDuckGo wraps results as //duckduckgo.com/l/?uddg=<encoded target>."""
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def _unwrap_google(href: str) -> str:
    """Google wraps results as /url?q=<encoded target>."""
    parsed = urlparse(href)
    if parsed.path == "/url":
        target = parse_qs(parsed.query).get("q")
        if target:
            return target[0]
    return href


def _unwrap_bing(href: str) -> str:
    """Bing occasionally wraps results as /ck/a?...&u=a1<base64 target>."""
    parsed = urlparse(href)
    if not parsed.netloc.endswith("bing.com") or not parsed.path.startswith("/ck/a"):
        return href
    encoded = parse_qs(parsed.query).get("u", [""])[0]
    if not encoded.startswith("a1"):
        return href
    payload = encoded[2:]
    payload += "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(payload).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return href


# ---------------------------------------------------------------- request side


def _duckduckgo_request(query: str, limit: int) -> EngineRequest:
    return EngineRequest(
        url="https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=_headers(),
    )


def _baidu_request(query: str, limit: int) -> EngineRequest:
    headers = _headers()
    headers["Referer"] = "https://www.baidu.com/"
    return EngineRequest(
        url="https://www.baidu.com/s",
        params={"wd": query, "rn": max(10, min(limit, 50))},
        headers=headers,
    )


def _google_request(query: str, limit: int) -> EngineRequest:
    return EngineRequest(
        url="https://www.google.com/search",
        params={"q": query, "num": max(10, min(limit, 20)), "hl": "zh-CN"},
        headers=_headers(),
    )


def _bing_request(query: str, limit: int) -> EngineRequest:
    """Bing China (cn.bing.com) is reachable in mainland China."""
    return EngineRequest(
        url="https://cn.bing.com/search",
        params={"q": query, "count": max(10, min(limit, 20))},
        headers=_headers(),
    )


def _so_request(query: str, limit: int) -> EngineRequest:
    return EngineRequest(
        url="https://www.so.com/s",
        params={"q": query},
        headers=_headers(),
    )


def _wechat_request(query: str, limit: int) -> EngineRequest:
    """Sogou WeChat search: article-only vertical search over mp.weixin.qq.com."""
    headers = _headers()
    headers["Referer"] = "https://weixin.sogou.com/"
    return EngineRequest(
        url="https://weixin.sogou.com/weixin",
        params={"type": 2, "query": query, "ie": "utf8"},
        headers=headers,
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


_REQUESTS: dict[str, Callable[[str, int], EngineRequest]] = {
    "duckduckgo": _duckduckgo_request,
    "baidu": _baidu_request,
    "google": _google_request,
    "bing": _bing_request,
    "360": _so_request,
    "wechat": _wechat_request,
}


# ----------------------------------------------------------------- parsing side


def parse_duckduckgo(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("div.result"):
        if "result--ad" in (node.get("class") or []):
            continue
        link = node.select_one("a.result__a")
        if link is None:
            continue
        url = _unwrap_duckduckgo(_resolve(link.get("href"), "https://duckduckgo.com"))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        snippet_el = node.select_one(".result__snippet")
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(link.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_baidu(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("div.result, div.c-container"):
        # Drop Baidu's promoted slots and internal "more results" links.
        classes = " ".join(node.get("class") or [])
        if "ec-" in classes or "EC_result" in classes:
            continue
        link = node.select_one("h3 a") or node.select_one("a[href]")
        if link is None:
            continue
        href = link.get("href")
        url = _resolve(href, "https://www.baidu.com")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        parsed = urlparse(url)
        if "baidu.php" in url:
            continue
        if parsed.netloc in {"www.baidu.com", "m.baidu.com"} and not parsed.path.startswith(
            "/link"
        ):
            continue
        snippet_el = node.select_one(
            "div[class*='summary-text'], div.cos-line-clamp-2, div.c-abstract, "
            "div[class*='content-right'], div.c-span-last, span.c-color-text"
        )
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(link.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_google(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("div.g, div.MjjYud"):
        heading = node.select_one("h3")
        if heading is None:
            continue
        anchor = heading.find_parent("a")
        if anchor is None or not anchor.get("href"):
            anchor = next(
                (a for a in node.select("a[href]") if a.find("h3") is heading),
                None,
            )
        if anchor is None:
            continue
        url = _unwrap_google(_resolve(anchor.get("href"), "https://www.google.com"))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        snippet_el = node.select_one(
            "div.VwiC3b, div.IsZvec, span.aCOpRe, div[data-sncf]"
        )
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(heading.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_bing(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("li.b_algo"):
        link = node.select_one("h2 a") or node.select_one("h3 a")
        if link is None or not link.get("href"):
            continue
        url = _unwrap_bing(_resolve(link.get("href"), "https://cn.bing.com"))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.netloc.endswith("bing.com"):
            continue
        snippet_el = node.select_one(
            "p.b_lineclamp2, p.b_lineclamp3, p.b_lineclamp4, div.b_caption p, p"
        )
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(link.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_360(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("li.res-list"):
        link = node.select_one("h3 a") or node.select_one("a[href]")
        if link is None:
            continue
        # 360 puts the real target in data-mdurl; href is a so.com redirect.
        raw = (link.get("data-mdurl") or "").strip()
        url = raw if raw.startswith(("http://", "https://")) else _resolve(
            link.get("href"), "https://www.so.com"
        )
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.netloc.endswith("360kan.com"):
            continue
        if parsed.netloc.endswith("so.com") and not parsed.path.startswith("/link"):
            continue
        snippet_el = node.select_one(
            "p.res-desc, div.res-rich, div.res-desc, p.res-comm-con, div.res-sub"
        )
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(link.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
            )
        )
        if len(results) >= limit:
            break
    return results


_TIME_CONVERT = re.compile(r"timeConvert\('(\d+)'\)")


def parse_wechat(html: str, limit: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen: set[str] = set()
    for node in soup.select("ul.news-list li"):
        link = node.select_one("h3 a")
        if link is None or not link.get("href"):
            continue
        url = _resolve(link.get("href"), "https://weixin.sogou.com")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        snippet_el = node.select_one("p.txt-info")
        published_at = None
        timestamp = _TIME_CONVERT.search(str(node))
        if timestamp:
            published_at = datetime.fromtimestamp(
                int(timestamp.group(1)), tz=timezone.utc
            ).isoformat(timespec="seconds")
        seen.add(url)
        results.append(
            SearchResult(
                title=_clean(link.get_text(" ")) or url,
                url=url,
                snippet=_clean(snippet_el.get_text(" ") if snippet_el else ""),
                published_at=published_at,
            )
        )
        if len(results) >= limit:
            break
    return results


_PARSERS: dict[str, Callable[[str, int], list[SearchResult]]] = {
    "duckduckgo": parse_duckduckgo,
    "baidu": parse_baidu,
    "google": parse_google,
    "bing": parse_bing,
    "360": parse_360,
    "wechat": parse_wechat,
}


# ------------------------------------------------------------------ public API


def parse_engine_names(raw: str | None) -> list[str]:
    """Turn ``APP_SEARCH_ENGINES`` into a de-duplicated, validated engine list."""
    names: list[str] = []
    for item in (raw or "").split(","):
        name = item.strip().lower()
        if not name:
            continue
        canonical = _ENGINE_ALIASES.get(name)
        if canonical is None:
            logger.warning("忽略不支持的搜索引擎: %s", name)
            continue
        if canonical not in names:
            names.append(canonical)
    return names


def build_engine_request(engine: str, query: str, limit: int) -> EngineRequest:
    builder = _REQUESTS.get(engine)
    if builder is None:
        raise SearchEngineError(f"不支持的搜索引擎: {engine}")
    return builder(query, limit)


def parse_engine_html(engine: str, html: str, limit: int) -> list[SearchResult]:
    parser = _PARSERS.get(engine)
    if parser is None:
        raise SearchEngineError(f"不支持的搜索引擎: {engine}")
    return parser(html, limit)
