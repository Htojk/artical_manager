"""RSS/Atom hot-topic parser."""

from __future__ import annotations

from urllib.parse import urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from app.article_generation.topic_selection.sources.base import HotSignal

_DATE_TAGS = {"pubdate", "published", "updated", "date"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_text: str, source_url: str = "", source_name: str = "") -> list[HotSignal]:
    root = ElementTree.fromstring(xml_text)
    signals: list[HotSignal] = []
    source = source_name or urlparse(source_url).netloc or "rss"
    for node in root.iter():
        if _local_name(node.tag) not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        summary = ""
        published_at: str | None = None
        for child in node:
            name = _local_name(child.tag)
            text = (child.text or "").strip()
            if name == "title" and text:
                title = text
            elif name == "link":
                link = (child.text or child.attrib.get("href") or "").strip()
            elif name in {"description", "summary", "content"} and text and not summary:
                summary = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)[:400]
            elif name in _DATE_TAGS and text and published_at is None:
                published_at = text
        if title:
            signals.append(
                HotSignal(
                    title=title,
                    source=source,
                    url=link,
                    published_at=published_at,
                    summary=summary,
                )
            )
    return signals
