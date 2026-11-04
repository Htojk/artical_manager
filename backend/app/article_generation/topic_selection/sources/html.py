"""HTML list-page hot-topic parser."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.article_generation.topic_selection.sources.base import (
    DEFAULT_ITEM_SELECTOR,
    HotSignal,
    HotSourceSpec,
)

_TITLE_FALLBACK = "h1 a, h2 a, h3 a, h4 a, a"
_SKIPPED_LINK_PREFIXES = ("javascript:", "#", "mailto:")


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def parse_html_list(html_text: str, spec: HotSourceSpec, limit: int = 20) -> list[HotSignal]:
    soup = BeautifulSoup(html_text, "html.parser")
    items = soup.select(spec.item_selector or DEFAULT_ITEM_SELECTOR)
    signals: list[HotSignal] = []
    for item in items:
        title_el = item.select_one(spec.title_selector or _TITLE_FALLBACK)
        if title_el is None:
            continue
        title = _clean(title_el.get_text(" "))
        if not title:
            continue

        link_el = item.select_one(spec.link_selector) if spec.link_selector else title_el
        href = link_el.get("href") if link_el is not None and link_el.name == "a" else None
        if not href:
            anchor = title_el.find_parent("a") if title_el.name != "a" else title_el
            if anchor is None:
                anchor = item.find("a")
            href = anchor.get("href") if anchor is not None else None
        href = (href or "").strip()
        if not href or href.lower().startswith(_SKIPPED_LINK_PREFIXES):
            continue

        time_el = item.select_one("time[datetime]") or item.select_one("time")
        published_at = None
        if time_el is not None:
            published_at = (time_el.get("datetime") or time_el.get_text(" ")).strip() or None

        signals.append(
            HotSignal(
                title=title,
                source=spec.name,
                url=urljoin(spec.url, href),
                published_at=published_at,
                summary=_clean(item.get_text(" "))[:400],
            )
        )
        if len(signals) >= limit:
            break
    return signals
