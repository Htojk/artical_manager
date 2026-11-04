"""Minimal WeChat Official Account (draft box) client."""

from __future__ import annotations

import time
import re
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.errors import AdapterError

DEFAULT_BASE_URL = "https://api.weixin.qq.com"
MEMECUB_IMAGE_HOST = "gpic.code-nav.cn"
MAX_ARTICLE_IMAGE_BYTES = 2 * 1024 * 1024


class WeChatClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._expires_at = 0.0
        self.http = httpx.Client(transport=transport, timeout=timeout)

    def close(self) -> None:
        self.http.close()

    def get_access_token(self, *, force: bool = False) -> str:
        if not force and self._token and time.time() < self._expires_at - 60:
            return self._token
        response = self.http.get(
            f"{self.base_url}/cgi-bin/token",
            params={
                "grant_type": "client_credential",
                "appid": self.app_id,
                "secret": self.app_secret,
            },
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        if "access_token" not in data:
            raise AdapterError(
                f"微信公众号获取 access_token 失败: {data.get('errmsg', data)}",
                details={"errcode": data.get("errcode")},
            )
        self._token = str(data["access_token"])
        self._expires_at = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def prepare_article_html(self, html: str) -> str:
        """Upload Memecub CDN images to WeChat before creating a draft."""
        pattern = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")', re.IGNORECASE)
        uploaded: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            url = match.group(2).replace("&amp;", "&")
            if urlparse(url).hostname != MEMECUB_IMAGE_HOST:
                return match.group(0)
            if url not in uploaded:
                uploaded[url] = self.upload_article_image(url)
            return match.group(1) + escape(uploaded[url], quote=True) + match.group(3)

        return pattern.sub(replace, html)

    def upload_article_image(self, image_url: str) -> str:
        parsed = urlparse(image_url)
        if (parsed.scheme != "https" or parsed.hostname != MEMECUB_IMAGE_HOST
                or parsed.username or parsed.password or parsed.port):
            raise AdapterError("Memecub 图片地址不合法")
        with self.http.stream("GET", image_url, follow_redirects=False) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"image/png", "image/jpeg", "image/gif"}:
                raise AdapterError("Memecub 图片格式不受微信公众号支持")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_ARTICLE_IMAGE_BYTES:
                    raise AdapterError("Memecub 图片超过公众号上传大小限制")
                chunks.append(chunk)
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}[content_type]
        response = self.http.post(
            f"{self.base_url}/cgi-bin/media/uploadimg",
            params={"access_token": self.get_access_token()},
            files={"media": (f"meme.{suffix}", b"".join(chunks), content_type)},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not str(data.get("url") or "").startswith(("https://", "http://")):
            message = data.get("errmsg", data) if isinstance(data, dict) else data
            raise AdapterError(f"公众号正文图片上传失败: {message}")
        return str(data["url"])

    def upload_cover_image(self, image_path: Path) -> str:
        """Upload a reusable cover as a permanent image material."""
        content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
            image_path.suffix.lower()
        )
        if content_type is None:
            raise AdapterError("公众号封面只支持 PNG 或 JPEG 图片")
        with image_path.open("rb") as image:
            response = self.http.post(
                f"{self.base_url}/cgi-bin/material/add_material",
                params={"access_token": self.get_access_token(), "type": "image"},
                files={"media": (image_path.name, image, content_type)},
            )
        response.raise_for_status()
        data = response.json()
        media_id = data.get("media_id") if isinstance(data, dict) else None
        if not media_id:
            message = data.get("errmsg", data) if isinstance(data, dict) else data
            raise AdapterError(f"公众号封面上传失败: {message}")
        return str(media_id)

    def create_draft(self, *, title: str, html: str, digest: str = "", thumb_media_id: str = "") -> str:
        if not thumb_media_id:
            raise AdapterError("微信公众号图文草稿缺少封面永久素材 ID")
        token = self.get_access_token()
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": "",
                    "digest": digest,
                    "content": html,
                    "content_source_url": "",
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                }
            ]
        }
        response = self.http.post(
            f"{self.base_url}/cgi-bin/draft/add",
            params={"access_token": token},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        media_id = data.get("media_id")
        if not media_id:
            raise AdapterError(
                f"微信公众号创建草稿失败: {data.get('errmsg', data)}",
                details={"errcode": data.get("errcode")},
            )
        return str(media_id)

    def submit_publish(self, media_id: str) -> str:
        token = self.get_access_token()
        response = self.http.post(
            f"{self.base_url}/cgi-bin/freepublish/submit",
            params={"access_token": token},
            json={"media_id": media_id},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errcode", 0) != 0:
            raise AdapterError(
                f"微信公众号发布失败: {data.get('errmsg', data)}",
                details={"errcode": data.get("errcode")},
            )
        return str(data.get("publish_id") or media_id)
