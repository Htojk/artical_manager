"""Fetch and extract the body of a single article linked from a hot signal."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.core.web import UrlFetcher

_REMOVED_TAGS = ("script", "style", "nav", "footer", "aside", "noscript", "form", "svg")


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _text_from(node) -> str:
    for tag in node.find_all(_REMOVED_TAGS):
        tag.decompose()
    paragraphs = [_clean(p.get_text(" ")) for p in node.find_all("p")]
    paragraphs = [text for text in paragraphs if text]
    if paragraphs:
        return "\n".join(paragraphs)
    return _clean(node.get_text(" "))


def _density_node(soup):
    best = None
    best_score = 0
    for node in soup.select("div, section, main"):
        score = sum(len(p.get_text(" ", strip=True)) for p in node.find_all("p"))
        if score > best_score:
            best, best_score = node, score
    return best


def extract_article_text(html_text: str, content_selector: str = "") -> str:
    """Extract body text: configured selector -> <article> -> density -> <body>."""
    soup = BeautifulSoup(html_text, "html.parser")
    if content_selector:
        selected = soup.select_one(content_selector)
        if selected is not None:
            return _text_from(selected)
    article = soup.find("article")
    if article is not None:
        return _text_from(article)
    dense = _density_node(soup)
    if dense is not None:
        return _text_from(dense)
    body = soup.body or soup
    return _text_from(body)


class ArticleContentFetcher:
    def __init__(
        self,
        *,
        fetcher: UrlFetcher | None = None,
        max_chars: int | None = None,
    ) -> None:
        self.fetcher = fetcher or UrlFetcher()
        self.max_chars = max_chars or get_settings().topic_article_max_chars

    def fetch(self, url: str, content_selector: str = "") -> str:
        html_text = self.fetcher.fetch(url)
        text = extract_article_text(html_text, content_selector)
        return text[: self.max_chars]
