"""WeChat Official Account adapter."""

from __future__ import annotations

from typing import Any

from app.core.errors import AdapterError
from app.platforms.base import (
    AdapterAvailability,
    AdapterCapabilities,
    ArticleForFormat,
    FormatResult,
    PlatformAdapter,
    PublishResult,
)
from app.platforms.wechat.client import WeChatClient
from app.platforms.wechat.covers import DEFAULT_COVER_STYLE, select_cover_style
from app.platforms.wechat.formatter import render_inline_html


class WeChatAdapter(PlatformAdapter):
    key = "wechat"
    display_name = "微信公众号"
    capabilities = AdapterCapabilities(
        format=True, publish=True, metrics=False, official_api=True, manual_fallback=True
    )

    def __init__(self, client_factory=None) -> None:
        self._client_factory = client_factory or (
            lambda credentials: WeChatClient(
                credentials["app_id"], credentials["app_secret"]
            )
        )

    def validate(self, credentials: dict[str, Any]) -> AdapterAvailability:
        if not (credentials.get("app_id") and credentials.get("app_secret")):
            return AdapterAvailability(
                available=False,
                mode="export_manual",
                reason="缺少公众号 AppID / AppSecret",
            )
        cover_ids = credentials.get("cover_media_ids")
        has_cover = isinstance(cover_ids, dict) and any(
            isinstance(value, str) and bool(value) for value in cover_ids.values()
        )
        if not credentials.get("thumb_media_id") and not has_cover:
            return AdapterAvailability(
                available=False,
                mode="export_manual",
                reason="缺少公众号封面永久素材 ID",
            )
        return AdapterAvailability(available=True, mode="api")

    def format(self, article: ArticleForFormat) -> FormatResult:
        html = render_inline_html(article.title, article.content_md, article.summary)
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary,
            tags=article.tags,
            content=html,
            format="html",
            metadata={"inline_styles": True},
        )

    def publish(self, artifact: FormatResult, credentials: dict[str, Any]) -> PublishResult:
        availability = self.validate(credentials)
        if not availability.available:
            return PublishResult(
                success=False,
                mode="export_manual",
                status="manual_required",
                error=availability.reason,
            )
        client = self._client_factory(credentials)
        try:
            selected_style = select_cover_style(artifact)
            cover_ids = credentials.get("cover_media_ids")
            cover_ids = cover_ids if isinstance(cover_ids, dict) else {}
            selected_cover = cover_ids.get(selected_style)
            if not isinstance(selected_cover, str) or not selected_cover:
                selected_cover = credentials.get("thumb_media_id") or next(
                    (value for value in cover_ids.values() if isinstance(value, str) and value), ""
                )
                selected_style = "default" if selected_cover else DEFAULT_COVER_STYLE
            prepare_html = getattr(client, "prepare_article_html", None)
            html = prepare_html(artifact.content) if callable(prepare_html) else artifact.content
            media_id = client.create_draft(
                title=artifact.title,
                html=html,
                digest=artifact.summary,
                thumb_media_id=selected_cover,
            )
            if credentials.get("publish_mode", "draft") == "publish":
                remote_id = client.submit_publish(media_id)
                status = "published"
            else:
                remote_id = media_id
                status = "draft"
            return PublishResult(
                success=True,
                remote_id=remote_id,
                status=status,
                mode="api",
                raw={"media_id": media_id, "cover_style": selected_style, "cover_media_id": selected_cover},
            )
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"微信公众号发布异常: {exc}") from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
