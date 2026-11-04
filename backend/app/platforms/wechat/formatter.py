"""Markdown to inline-styled WeChat HTML."""

from __future__ import annotations

from html import escape

import markdown as markdown_lib

_STYLES = {
    "<h1>": '<h1 style="font-size:22px;font-weight:700;line-height:1.4;margin:24px 0 12px;color:#1f2328;">',
    "<h2>": '<h2 style="font-size:19px;font-weight:700;line-height:1.5;margin:22px 0 10px;color:#1f2328;">',
    "<h3>": '<h3 style="font-size:17px;font-weight:600;line-height:1.5;margin:18px 0 8px;color:#1f2328;">',
    "<p>": '<p style="font-size:16px;line-height:1.9;margin:12px 0;color:#333;">',
    "<li>": '<li style="font-size:16px;line-height:1.9;margin:6px 0;color:#333;">',
    "<blockquote>": '<blockquote style="border-left:3px solid #d0d7de;padding:8px 14px;margin:14px 0;color:#57606a;background:#f6f8fa;">',
    "<pre>": '<pre style="background:#f6f8fa;padding:14px;border-radius:6px;overflow-x:auto;font-size:14px;line-height:1.6;">',
    "<code>": '<code style="background:#f0f2f5;padding:2px 5px;border-radius:4px;font-size:14px;">',
    "<img": '<img style="max-width:100%;height:auto;border-radius:6px;"',
    "<table>": '<table style="border-collapse:collapse;width:100%;margin:14px 0;font-size:14px;">',
    "<th>": '<th style="border:1px solid #d0d7de;padding:8px;background:#f6f8fa;text-align:left;">',
    "<td>": '<td style="border:1px solid #d0d7de;padding:8px;">',
}


def markdown_to_html(markdown_text: str) -> str:
    body = markdown_lib.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "sane_lists"],
    )
    for tag, styled in _STYLES.items():
        body = body.replace(tag, styled)
    return body


def render_inline_html(title: str, markdown_text: str, summary: str = "") -> str:
    body = markdown_to_html(markdown_text)
    intro = (
        f'<p style="font-size:15px;line-height:1.8;color:#57606a;margin:0 0 18px;">{escape(summary)}</p>'
        if summary
        else ""
    )
    return (
        '<section style="max-width:677px;margin:0 auto;padding:8px 4px;font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',sans-serif;">'
        f"{intro}{body}"
        "</section>"
    )
