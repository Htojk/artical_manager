"""Article body extraction used after topic selection."""

from __future__ import annotations

from app.article_generation.topic_selection.articles import (
    ArticleContentFetcher,
    extract_article_text,
)


def test_extract_respects_content_selector():
    html = """
    <html><body>
      <div class="body"><p>选择器命中的正文。</p></div>
      <article><p>不应被采用的正文。</p></article>
    </body></html>
    """
    assert extract_article_text(html, ".body") == "选择器命中的正文。"


def test_extract_prefers_article_element():
    html = """
    <html><body>
      <div><p>页面其他内容。</p></div>
      <article><p>文章正文第一段。</p><p>文章正文第二段。</p></article>
    </body></html>
    """
    assert extract_article_text(html) == "文章正文第一段。\n文章正文第二段。"


def test_extract_uses_text_density_without_article():
    long_text = "这是较长的一段正文内容。" * 5
    html = f"""
    <html><body>
      <div class="sidebar"><p>短。</p></div>
      <div class="content"><p>{long_text}</p><p>第二段。</p></div>
    </body></html>
    """
    assert extract_article_text(html).startswith(long_text)


def test_extract_falls_back_to_body():
    html = "<html><body>没有标签包裹的纯文本正文</body></html>"
    assert extract_article_text(html) == "没有标签包裹的纯文本正文"


def test_content_fetcher_truncates_body():
    html = "<html><body><article><p>" + "长" * 200 + "</p></article></body></html>"

    class FakeFetcher:
        def fetch(self, url: str) -> str:
            assert url == "https://example.com/a"
            return html

    fetcher = ArticleContentFetcher(fetcher=FakeFetcher(), max_chars=50)
    text = fetcher.fetch("https://example.com/a")
    assert len(text) == 50
