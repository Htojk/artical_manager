"""HTTP page fetching shared by research and topic selection."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.core.tracing import trace_span

USER_AGENT = "ArticleAutopilot/0.1 (+local)"


class UrlFetcher:
    def __init__(self, *, timeout: float = 15.0, max_bytes: int = 200_000) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if not parsed.scheme.startswith("http"):
            return False
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = httpx.get(robots_url, timeout=5.0, headers={"User-Agent": USER_AGENT})
            if response.status_code >= 400:
                return True
            parser.parse(response.text.splitlines())
            return parser.can_fetch("*", url)
        except Exception:  # noqa: BLE001 - missing robots should not block
            return True

    def fetch(self, url: str) -> str:
        with trace_span("fetch.url", input={"url": url}) as span:
            try:
                if not self._robots_allowed(url):
                    raise PermissionError(f"robots.txt 不允许抓取: {url}")
                response = httpx.get(
                    url,
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    },
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text" not in content_type and "json" not in content_type:
                    raise ValueError(f"不支持的内容类型: {content_type}")
            except Exception as exc:
                if span is not None:
                    span.update(
                        output={"url": url, "status": "error", "error": str(exc)},
                        level="ERROR",
                        status_message=str(exc),
                    )
                raise
            text = response.text[: self.max_bytes]
            if span is not None:
                span.update(
                    output={
                        "url": url,
                        "status": response.status_code,
                        "chars": len(text),
                        "truncated": len(response.text) > self.max_bytes,
                    }
                )
            return text
