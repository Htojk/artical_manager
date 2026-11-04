"""Memecub licensing, placement, and WeChat image upload tests."""

import httpx

from app.article_generation.formatting.memecub import MemecubClient, enrich_markdown
from app.platforms.wechat.client import WeChatClient


ARTICLE = "\n\n".join(
    f"这是第 {number} 段正文，讲述一个让读者有共鸣的真实观察和情绪变化。"
    for number in range(1, 7)
)


def _image(number: int, *, commercial: bool = True, attribution: str = "来源 A") -> dict:
    return {
        "title": f"表情 {number}",
        "url": f"https://gpic.code-nav.cn/meme/{number}.png",
        "license": {"commercial_use": commercial, "attribution_required": True},
        "attribution": attribution,
    }


def test_inserts_two_distinct_licensed_images_with_attribution():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [_image(1), _image(2)]})

    client = MemecubClient("test-key", transport=httpx.MockTransport(handler))
    content, warning = enrich_markdown(ARTICLE, article_id="a", client=client)
    assert warning is None
    assert content.count("![表情") == 2
    assert content.count("图片来源：来源 A") == 2
    assert "![表情 1]" in content and "![表情 2]" in content
    assert all(request.headers["authorization"] == "Bearer test-key" for request in calls)
    assert all(request.url.params["commercial"] == "1" for request in calls)
    client.close()


def test_insufficient_commercial_images_preserves_article():
    def handler(_request):
        return httpx.Response(200, json={"data": [_image(1, commercial=False),
                                                   _image(2, attribution="")]})

    client = MemecubClient("test-key", transport=httpx.MockTransport(handler))
    content, warning = enrich_markdown(ARTICLE, article_id="a", client=client)
    assert content == ARTICLE
    assert "不足两张" in warning
    client.close()


def test_fenced_code_and_short_article_are_not_image_positions():
    article = ARTICLE.replace("\n\n", "\n\n```python\nprint('hello')\n```\n\n", 1)
    client = MemecubClient("test-key", transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"data": [_image(1), _image(2)]})
    ))
    content, warning = enrich_markdown(article, article_id="a", client=client)
    assert warning is None
    assert "```python\nprint('hello')\n```\n\n![" not in content
    short, warning = enrich_markdown("只有一段。", article_id="a", client=client)
    assert short == "只有一段。" and warning
    client.close()


def test_wechat_uploads_memecub_images_before_draft():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        if request.url.path == "/meme/1.png":
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")
        if request.url.path == "/cgi-bin/media/uploadimg":
            assert b"png" in request.read()
            return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/uploaded.png"})
        return httpx.Response(404)

    client = WeChatClient("app", "secret", transport=httpx.MockTransport(handler))
    html = '<p><img src="https://gpic.code-nav.cn/meme/1.png"></p>'
    prepared = client.prepare_article_html(html)
    assert 'src="https://mmbiz.qpic.cn/uploaded.png"' in prepared
    assert "/cgi-bin/media/uploadimg" in calls
    client.close()


def test_formatting_reuses_same_two_images_across_platforms(client_env, article_factory, monkeypatch):
    from app.article_generation.formatting import service as formatting_module
    from app.article_generation.formatting.service import FormattingService
    from app.article_generation.writing.service import WritingService
    from app.core.security import CredentialCipher, CredentialService
    from app.skills.manager import SkillManager

    article_id = article_factory(platforms=["mock", "zhihu"])
    client_env.settings.memecub_enabled = True
    client_env.settings.memecub_api_key = "test-key"
    monkeypatch.setattr(formatting_module, "get_settings", lambda: client_env.settings)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [_image(1), _image(2)]})

    client = MemecubClient("test-key", transport=httpx.MockTransport(handler))
    with client_env.session_factory() as session:
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).user_edit(article_id, content_md=ARTICLE, summary="摘要")
        service = FormattingService(
            session, client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
            memecub_client=client,
        )
        result = service.format_article(article_id)
        assert not result.errors and not result.warnings
        assert len(result.outputs) == 2
        assert all(output.content.count("![表情") == 2 for output in result.outputs)
        first_content = result.outputs[0].content
        first_request_count = len(requests)
        retried = service.retry(article_id, "mock")
        assert retried.content == first_content
        assert len(requests) == first_request_count
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).user_edit(article_id, content_md=ARTICLE + "\n\n这是新增段落，用于确认稿件修改后会重新检索和选择配图。", summary="摘要")
        refreshed = service.format_article(article_id, ["mock"])
        assert not refreshed.warnings
        assert len(requests) > first_request_count
    client.close()


def test_formatting_warning_survives_reload(client_env, article_factory, monkeypatch):
    from app.article_generation.formatting import service as formatting_module
    from app.article_generation.formatting.service import FormattingService
    from app.article_generation.writing.service import WritingService
    from app.core.security import CredentialCipher, CredentialService
    from app.skills.manager import SkillManager

    article_id = article_factory(platforms=["mock"])
    client_env.settings.memecub_enabled = True
    client_env.settings.memecub_api_key = "test-key"
    monkeypatch.setattr(formatting_module, "get_settings", lambda: client_env.settings)
    client = MemecubClient("test-key", transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"data": []})
    ))
    with client_env.session_factory() as session:
        WritingService(
            session, client_env.llm, SkillManager(session, client_env.skill_registry)
        ).user_edit(article_id, content_md=ARTICLE, summary="摘要")
        service = FormattingService(
            session, client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
            memecub_client=client,
        )
        result = service.format_article(article_id)
        assert result.warnings
    with client_env.session_factory() as session:
        service = FormattingService(
            session, client_env.registry,
            CredentialService(session, CredentialCipher(client_env.settings)),
        )
        output = service.list_outputs(article_id)[0]
        assert output.warning == result.warnings[0]
        assert "![" not in output.content
    response = client_env.client.get(f"/api/articles/{article_id}/stages/formatting")
    assert response.status_code == 200
    assert response.json()["content"]["outputs"][0]["warning"] == result.warnings[0]
    client.close()
