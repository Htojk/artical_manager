"""Upload the four account covers once and cache their WeChat material IDs."""

from __future__ import annotations

import logging

from app.core.db import get_session_factory
from app.core.security import CredentialService
from app.platforms.wechat.client import WeChatClient
from app.platforms.wechat.covers import COVER_FILES, cover_path


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    paths = {style: cover_path(style) for style in COVER_FILES}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"缺少公众号封面图片: {', '.join(missing)}")

    with get_session_factory()() as session:
        credentials = CredentialService(session)
        payload = credentials.get("wechat")
        if not (payload.get("app_id") and payload.get("app_secret")):
            raise RuntimeError("请先配置公众号 AppID 和 AppSecret")
        cover_ids = payload.get("cover_media_ids")
        cover_ids = dict(cover_ids) if isinstance(cover_ids, dict) else {}
        client = WeChatClient(payload["app_id"], payload["app_secret"])
        try:
            for style, path in paths.items():
                if cover_ids.get(style):
                    print(f"{style}: 已有素材，跳过")
                    continue
                cover_ids[style] = client.upload_cover_image(path)
                credentials.set("wechat", {**payload, "cover_media_ids": cover_ids})
                print(f"{style}: 上传成功")
        finally:
            client.close()


if __name__ == "__main__":
    main()
