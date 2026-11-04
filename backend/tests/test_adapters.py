"""Adapter contract, discovery and platform-specific behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import AdapterError
from app.platforms.base import (
    AdapterAvailability,
    ArticleForFormat,
    FormatResult,
    PlatformAdapter,
)
from app.platforms.registry import PlatformRegistry as _RegistryForContract
from app.platforms.csdn.adapter import CsdnAdapter
from app.platforms.juejin.adapter import JuejinAdapter
from app.platforms.mock.adapter import MockAdapter
from app.platforms.registry import PlatformRegistry
from app.platforms.wechat.adapter import WeChatAdapter
from app.platforms.wechat.client import WeChatClient
from app.platforms.wechat.covers import COVER_FILES, cover_path, select_cover_style
from app.platforms.zhihu.adapter import ZhihuAdapter


def article(**overrides):
    values = {
        "article_id": "a1",
        "title": "测试标题",
        "content_md": "正文第一段\n\n## 小节\n\n更多内容",
        "summary": "摘要",
        "tags": ["AI", "测试"],
    }
    values.update(overrides)
    return ArticleForFormat(**values)


def test_registry_discovery_and_capabilities():
    registry = PlatformRegistry()
    found = registry.discover()
    keys = {adapter.key for adapter in found}
    assert {"mock", "wechat", "zhihu", "juejin", "csdn"} <= keys
    assert "mock" in [adapter.key for adapter in registry.with_capability("publish")]
    assert registry.require("mock").display_name
    with pytest.raises(KeyError):
        registry.require("nope")
    assert registry.get("nope") is None


def test_registry_rejects_adapter_without_key():
    registry = PlatformRegistry()

    class BadAdapter(PlatformAdapter):
        key = ""

        def validate(self, credentials):
            return None

        def format(self, article):
            return None

        def publish(self, artifact, credentials):
            return None

    with pytest.raises(ValueError):
        registry.register(BadAdapter())


def test_registry_discovers_external_package(tmp_path):
    package = tmp_path / "demo"
    package.mkdir()
    (package / "adapter.py").write_text(
        "from app.platforms.base import PlatformAdapter, AdapterAvailability\n"
        "class DemoAdapter(PlatformAdapter):\n"
        "    key = 'demo'\n"
        "    display_name = 'Demo'\n"
        "    def validate(self, credentials):\n"
        "        return AdapterAvailability(available=True)\n"
        "    def format(self, article):\n"
        "        raise NotImplementedError\n"
        "    def publish(self, artifact, credentials):\n"
        "        raise NotImplementedError\n",
        encoding="utf-8",
    )
    registry = PlatformRegistry()
    registry.discover(paths=[tmp_path])
    assert registry.get("demo") is not None


def test_mock_adapter_roundtrip():
    adapter = MockAdapter()
    assert adapter.validate({}).available
    artifact = adapter.format(article())
    assert artifact.content.startswith("# 测试标题")
    result = adapter.publish(artifact, {})
    assert result.success
    assert result.remote_id.startswith("mock-")
    assert adapter.fetch_metrics(SimpleNamespace(remote_id=result.remote_id), {}).views > 0


def test_markdown_platforms():
    source = article(content_md="没有一级标题的正文")
    zhihu = ZhihuAdapter().format(source)
    assert zhihu.content.startswith("# 测试标题")
    assert zhihu.metadata["topics"] == ["AI", "测试"]

    csdn = CsdnAdapter().format(source)
    assert csdn.content.startswith("---\ntitle: 测试标题")
    assert "categories: [技术分享]" in csdn.content

    juejin = JuejinAdapter().format(source)
    assert "tags: [AI, 测试]" in juejin.content

    for adapter in (ZhihuAdapter(), CsdnAdapter(), JuejinAdapter()):
        result = adapter.publish(adapter.format(source), {})
        assert result.status == "manual_required"
        assert result.success is False


class FakeWeChatClient:
    def __init__(self):
        self.created = []
        self.submitted = []
        self.closed = False

    def create_draft(self, *, title, html, digest="", thumb_media_id=""):
        self.created.append((title, html, digest, thumb_media_id))
        return "media-1"

    def submit_publish(self, media_id):
        self.submitted.append(media_id)
        return "publish-1"

    def close(self):
        self.closed = True


def test_wechat_requires_credentials_and_formats_html():
    adapter = WeChatAdapter()
    assert not adapter.validate({}).available
    assert not adapter.validate({"app_id": "a", "app_secret": "b"}).available
    assert adapter.validate({"app_id": "a", "app_secret": "b", "thumb_media_id": "thumb-1"}).available

    artifact = adapter.format(article(content_md="# 一级标题\n\n正文第一段"))
    assert artifact.format == "html"
    assert "<h1 style=" in artifact.content
    assert "摘要" in artifact.content

    result = adapter.publish(artifact, {})
    assert result.status == "manual_required"
    assert "AppID" in result.error


def test_wechat_draft_and_publish_modes():
    client = FakeWeChatClient()
    adapter = WeChatAdapter(client_factory=lambda credentials: client)
    draft = adapter.publish(
        adapter.format(article()), {"app_id": "a", "app_secret": "b", "thumb_media_id": "thumb-1", "publish_mode": "draft"}
    )
    assert draft.status == "draft"
    assert draft.remote_id == "media-1"
    assert client.created[0][3] == "thumb-1"
    assert client.closed

    published = adapter.publish(
        adapter.format(article()), {"app_id": "a", "app_secret": "b", "thumb_media_id": "thumb-1", "publish_mode": "publish"}
    )
    assert published.status == "published"
    assert published.remote_id == "publish-1"
    assert client.submitted == ["media-1"]


@pytest.mark.parametrize(
    ("title", "summary", "expected"),
    [
        ("两个 AI 互相甩锅的虚构剧场", "一场搞笑脑洞", "entertainment"),
        ("开源模型推理架构拆解", "算法和算力变化", "technology"),
        ("AI 帮老人看病会带来什么变化", "社区医疗服务", "everyday_life"),
        ("用 AI 整理会议纪要和周报", "提升办公效率", "workplace"),
    ],
)
def test_wechat_cover_selection(title, summary, expected):
    artifact = WeChatAdapter().format(article(title=title, summary=summary))
    assert select_cover_style(artifact) == expected
    assert cover_path(expected).name == COVER_FILES[expected]


def test_wechat_uses_cover_matching_article_tone():
    client = FakeWeChatClient()
    adapter = WeChatAdapter(client_factory=lambda _credentials: client)
    result = adapter.publish(
        adapter.format(article(title="AI 帮老人看病", summary="社区医疗服务")),
        {
            "app_id": "a", "app_secret": "b", "thumb_media_id": "old-cover",
            "cover_media_ids": {
                "entertainment": "cover-fun", "technology": "cover-tech",
                "everyday_life": "cover-life", "workplace": "cover-work",
            },
        },
    )
    assert result.status == "draft"
    assert result.raw["cover_style"] == "everyday_life"
    assert client.created[0][3] == "cover-life"


def test_wechat_client_requests():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.read().decode()))
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        if request.url.path == "/cgi-bin/draft/add":
            return httpx.Response(200, json={"media_id": "media-9"})
        if request.url.path == "/cgi-bin/freepublish/submit":
            return httpx.Response(200, json={"errcode": 0, "publish_id": "pub-9"})
        return httpx.Response(404)

    client = WeChatClient(
        "app", "secret", base_url="https://wx.test", transport=httpx.MockTransport(handler)
    )
    media_id = client.create_draft(title="标题", html="<p>正文</p>", digest="摘要", thumb_media_id="thumb-1")
    assert media_id == "media-9"
    assert client.submit_publish(media_id) == "pub-9"
    assert seen[0][1] == "/cgi-bin/token"
    assert json.loads(seen[1][2])["articles"][0]["title"] == "标题"
    assert json.loads(seen[1][2])["articles"][0]["thumb_media_id"] == "thumb-1"
    client.close()


def test_wechat_uploads_permanent_cover(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"sample-image")
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        assert request.url.params["type"] == "image"
        assert b"sample-image" in request.read()
        return httpx.Response(200, json={"media_id": "cover-1"})

    client = WeChatClient("app", "secret", base_url="https://wx.test", transport=httpx.MockTransport(handler))
    assert client.upload_cover_image(cover) == "cover-1"
    assert paths == ["/cgi-bin/token", "/cgi-bin/material/add_material"]
    client.close()


def test_wechat_client_error_response():
    def handler(_request):
        return httpx.Response(200, json={"errcode": 40013, "errmsg": "invalid appid"})

    client = WeChatClient(
        "app", "secret", base_url="https://wx.test", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AdapterError):
        client.get_access_token()
    client.close()


def test_adapter_contract_all_registered():
    """Every discovered adapter honours the shared format/publish/metrics contract."""
    import inspect

    registry = _RegistryForContract()
    registry.discover()
    assert registry.keys()
    for adapter in registry.all():
        assert adapter.key and adapter.display_name
        assert isinstance(adapter.capabilities, type(adapter.capabilities))
        availability = adapter.validate({})
        assert isinstance(availability, AdapterAvailability)
        result = adapter.format(article(target_platform=adapter.key))
        assert isinstance(result, FormatResult)
        assert result.platform == adapter.key
        assert isinstance(result.content, str)
        assert result.format in {"markdown", "html"}
        assert callable(adapter.fetch_metrics)
        inspect.signature(adapter.publish).bind(result, {})
        if not adapter.capabilities.publish:
            publish = adapter.publish(result, {})
            assert publish.success is False or publish.status == "manual_required"
