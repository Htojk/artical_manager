"""HTTP API integration tests using the fake LLM and in-memory platform."""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import select

from app.api.events import _frame
from app.article_generation.workflow.runner import WorkflowRunner
from app.core.constants import STAGE_ORDER, Stage
from app.models.article import ReviewDecision, ReviewReport, WorkflowRun


def test_health_and_openapi(client_env):
    client = client_env.client
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    schema = client.get("/openapi.json").json()
    assert "/api/articles" in schema["paths"]
    assert "/api/articles/{article_id}/stages" in schema["paths"]
    assert schema["info"]["title"]

    root = client.get("/").json()
    assert root["docs"] == "/docs"


def test_error_shape(client_env):
    response = client_env.client.get("/api/articles/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

    invalid = client_env.client.post("/api/articles", json={"topic_mode": "nope"})
    assert invalid.status_code == 422
    body = invalid.json()
    assert body["code"] == "validation_error"
    assert body["details"]


def test_article_and_topic_crud(client_env):
    client = client_env.client
    created = client.post(
        "/api/articles",
        json={
            "title": "API 创建的文章",
            "target_platforms": ["mock"],
            "publish_confirmation": False,
        },
    )
    assert created.status_code == 201
    data = created.json()
    article_id = data["article"]["id"]
    assert data["article"]["current_topic_id"]
    assert len(data["topics"]) == 1

    listing = client.get("/api/articles").json()
    assert listing["total"] == 1

    detail = client.get(f"/api/articles/{article_id}").json()
    assert detail["article"]["title"] == "API 创建的文章"

    patched = client.patch(f"/api/articles/{article_id}", json={"title": "改标题"})
    assert patched.json()["title"] == "改标题"

    recommended = client.post(f"/api/articles/{article_id}/topics/recommend", json={})
    assert recommended.status_code == 200
    topics = recommended.json()["items"]
    assert len(topics) == 5
    assert topics[0]["discussion_score"] == 80
    assert topics[0]["discussion_reason"]

    manual = client.post(
        f"/api/articles/{article_id}/topics",
        json={"title": "补充选题", "angle": "新角度"},
    )
    assert manual.status_code == 201
    topic_id = manual.json()["id"]

    updated = client.patch(f"/api/topics/{topic_id}", json={"title": "补充选题 v2"})
    assert updated.json()["title"] == "补充选题 v2"
    assert client.get(f"/api/topics/{topic_id}").status_code == 200

    selected = client.post(f"/api/topics/{topic_id}/select")
    assert selected.status_code == 200
    assert selected.json()["article"]["current_topic_id"] == topic_id
    assert selected.json()["source_fetch"] == {
        "ok": False,
        "source_id": None,
        "title": "",
        "error": None,
        "reason": "候选未关联文章链接",
    }

    deleted_topic = client.delete(f"/api/topics/{topic_id}")
    assert deleted_topic.status_code == 204


def _topic_with_signal(client_env, article_id: str, url: str) -> str:
    from app.article_generation.topic_selection.service import TopicService

    with client_env.session_factory() as session:
        service = TopicService(session, client_env.llm)
        topic = service.create_manual(article_id, title="关联热点的 API 选题")
        topic.hot_signals = [
            {"title": "热点文章", "source": "示例源", "url": url}
        ]
        session.commit()
        return topic.id


def test_select_topic_returns_source_fetch_success(client_env, monkeypatch):
    from app.article_generation.topic_selection.articles import ArticleContentFetcher

    client = client_env.client
    created = client.post("/api/articles", json={"target_platforms": ["mock"]})
    article_id = created.json()["article"]["id"]
    topic_id = _topic_with_signal(
        client_env, article_id, "https://example.com/articles/hot"
    )
    monkeypatch.setattr(
        ArticleContentFetcher,
        "fetch",
        lambda self, url, content_selector="": f"抓取的正文：{url}",
    )

    response = client.post(f"/api/articles/{article_id}/topics/{topic_id}/select")

    assert response.status_code == 200
    fetch = response.json()["source_fetch"]
    assert fetch["ok"] is True
    assert fetch["source_id"]
    assert fetch["error"] is None
    sources = client.get(f"/api/articles/{article_id}/sources").json()["items"]
    assert sources[0]["added_by"] == "topic"
    assert sources[0]["snippet"] == "抓取的正文：https://example.com/articles/hot"


def test_select_topic_reports_fetch_failure(client_env, monkeypatch):
    from app.article_generation.topic_selection.articles import ArticleContentFetcher

    client = client_env.client
    created = client.post("/api/articles", json={"target_platforms": ["mock"]})
    article_id = created.json()["article"]["id"]
    topic_id = _topic_with_signal(
        client_env, article_id, "https://example.com/articles/timeout"
    )

    def fail(self, url, content_selector=""):
        raise TimeoutError("抓取超时")

    monkeypatch.setattr(ArticleContentFetcher, "fetch", fail)

    response = client.post(f"/api/articles/{article_id}/topics/{topic_id}/select")

    assert response.status_code == 200
    assert response.json()["article"]["current_topic_id"] == topic_id
    assert response.json()["source_fetch"]["ok"] is False
    assert "抓取超时" in response.json()["source_fetch"]["error"]


def test_run_stage_timeline_and_editing(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client = client_env.client

    started = client.post(f"/api/articles/{article_id}/run")
    assert started.status_code == 202
    run = started.json()
    assert run["status"] == "pending"

    client_env.runner.execute_sync(run["id"], initial=True)
    fetched = client.get(f"/api/runs/{run['id']}").json()
    assert fetched["status"] == "completed"

    timeline = client.get(f"/api/articles/{article_id}/stages").json()
    assert [item["stage"] for item in timeline["stages"]] == list(STAGE_ORDER)
    assert all(item["status"] == "completed" for item in timeline["stages"])
    assert timeline["stages"][0]["label"] == "选题"

    for stage in STAGE_ORDER:
        detail = client.get(f"/api/articles/{article_id}/stages/{stage}")
        assert detail.status_code == 200
        assert detail.json()["stage_run"]["status"] == "completed"

    writing = client.get(f"/api/articles/{article_id}/stages/writing").json()
    assert writing["content"]["latest"]["content_md"]
    review = client.get(f"/api/articles/{article_id}/stages/review").json()
    assert review["content"]["latest_decision"] is None
    assert client.get(f"/api/articles/{article_id}/stages/unknown").status_code == 422

    title_stage = client.get(
        f"/api/articles/{article_id}/stages/title_optimization"
    ).json()
    latest_title = title_stage["content"]["latest"]
    assert latest_title["selected_title"] == "测试标题：AI 工程实践的三条经验"
    assert len(latest_title["candidates"]) == 3

    picked = client.put(
        f"/api/articles/{article_id}/stages/title_optimization",
        json={"title": "用户选定的标题"},
    )
    assert picked.status_code == 200
    assert picked.json()["created_by"] == "user"
    assert picked.json()["selected_title"] == "用户选定的标题"
    assert (
        client.get(f"/api/articles/{article_id}").json()["article"]["title"]
        == "用户选定的标题"
    )

    outline = client.get(f"/api/articles/{article_id}/stages/outline").json()["content"]["latest"]
    edited = client.put(
        f"/api/articles/{article_id}/stages/outline",
        json={"content": {**outline["content"], "hook": "用户修改的钩子"}},
    )
    assert edited.status_code == 200
    assert edited.json()["version"] == outline["version"] + 1

    draft = client.put(
        f"/api/articles/{article_id}/stages/writing",
        json={"content_md": "用户修改后的正文", "summary": "新摘要"},
    )
    assert draft.status_code == 200
    assert draft.json()["created_by"] == "user"

    runs = client.get(f"/api/articles/{article_id}/runs").json()
    assert len(runs["items"]) == 1


def test_run_endpoint_schedules_workflow_on_event_loop(client_env, article_factory):
    """The HTTP route must leave a real runner able to schedule its task."""
    article_id = article_factory(platforms=["mock"])
    runner = WorkflowRunner(
        client_env.session_factory,
        client_env.llm,
        client_env.registry,
        client_env.skill_registry,
        settings=client_env.settings,
        search_tool=client_env.search_tool,
    )
    client_env.app.state.runner = runner

    started = client_env.client.post(f"/api/articles/{article_id}/run")
    assert started.status_code == 202
    run_id = started.json()["id"]

    deadline = time.monotonic() + 10
    status = "pending"
    while time.monotonic() < deadline:
        status = client_env.client.get(f"/api/runs/{run_id}").json()["status"]
        if status not in {"pending", "running"}:
            break
        time.sleep(0.05)
    assert status == "completed"


def test_run_requires_topic_and_conflict(client_env):
    client = client_env.client
    created = client.post(
        "/api/articles", json={"title": "", "topic_mode": "ai", "target_platforms": ["mock"]}
    )
    article_id = created.json()["article"]["id"]
    response = client.post(f"/api/articles/{article_id}/run")
    assert response.status_code == 422
    assert "选题" in response.json()["message"]


def test_format_publish_and_manual_fallback(client_env, article_factory):
    article_id = article_factory(platforms=["mock", "zhihu"])
    client = client_env.client
    client.put(
        f"/api/articles/{article_id}/stages/writing",
        json={"content_md": "# 正文\n\n内容", "summary": "摘要"},
    )
    formatted = client.post(
        f"/api/articles/{article_id}/formats", json={"platforms": ["mock", "zhihu"]}
    )
    assert formatted.status_code == 200
    assert {item["platform"] for item in formatted.json()["items"]} == {"mock", "zhihu"}
    assert client.get(f"/api/articles/{article_id}/formats").json()["items"]

    summary = client.get(f"/api/articles/{article_id}/confirm-summary").json()
    assert len(summary["platforms"]) == 2

    published = client.post(f"/api/articles/{article_id}/publish", json={})
    assert published.status_code == 200
    statuses = {item["platform"]: item["status"] for item in published.json()["items"]}
    assert statuses == {"mock": "published", "zhihu": "manual_required"}

    manual = client.post(
        f"/api/articles/{article_id}/publish/zhihu/manual",
        json={"url": "https://zhuanlan.zhihu.com/p/42"},
    )
    assert manual.status_code == 200
    assert manual.json()["status"] == "published"

    records = client.get(f"/api/articles/{article_id}/publish/records").json()["items"]
    assert len(records) == 2
    history = client.get(f"/api/articles/{article_id}/publish/history").json()["items"]
    assert any(row["platform"] == "mock" for row in history)
    assert client.get(f"/api/articles/{article_id}/publish/mock/history").status_code == 200

    raw = client.post(
        f"/api/articles/{article_id}/publish/zhihu/manual",
        json={"url": "not-a-url"},
    )
    assert raw.status_code == 200


def test_analytics_endpoints(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client = client_env.client
    client_env.runner.execute_sync(
        client_env.runner.start_run(article_id).id, initial=True
    )

    summary = client.get("/api/analytics/summary")
    assert summary.status_code == 200
    assert "views" in summary.json()["metrics"]

    performance = client.get("/api/analytics/performance").json()
    assert performance["items"]
    article = client.get(f"/api/analytics/articles/{article_id}")
    assert article.status_code == 200
    costs = client.get("/api/analytics/costs", params={"article_id": article_id}).json()
    assert "total_cost" in costs

    collected = client.post("/api/analytics/collect")
    assert collected.status_code == 200

    records = client.get(f"/api/articles/{article_id}/publish/records").json()["items"]
    record_id = records[0]["id"]
    metrics = client.post(
        f"/api/analytics/records/{record_id}/metrics",
        json={"views": 1234, "likes": 20, "comments": 3, "shares": 2, "revenue_cents": 500},
    )
    assert metrics.status_code == 201
    assert metrics.json()["views"] == 1234

    assert client.get(f"/api/analytics/articles/{article_id}").json()["metrics"]["views"] == 1234
    assert client.get("/api/analytics/articles/missing").status_code == 404


def test_skills_and_bindings(client_env):
    client = client_env.client
    items = client.get("/api/skills").json()["items"]
    slugs = [item["slug"] for item in items]
    assert "writing-style-tech-review" in slugs

    detail = client.get("/api/skills/writing-style-tech-review")
    assert detail.status_code == 200
    assert detail.json()["content"]
    assert detail.json()["standard_name"] == "writing-style-tech-review"
    assert detail.json()["resources"] == []

    created_skill = client.post(
        "/api/skills",
        json={
            "slug": "api-test-skill",
            "description": "接口测试技能",
            "display_name": "接口测试",
            "content": "## 要求\n只用于测试。",
            "applies_to": ["review"],
        },
    )
    assert created_skill.status_code == 201
    assert created_skill.json()["name"] == "接口测试"
    assert client.post(
        "/api/skills",
        json={"slug": "api-test-skill", "description": "重复"},
    ).status_code == 409
    assert client.post(
        "/api/skills",
        json={"slug": "Bad Slug", "description": "非法"},
    ).status_code == 422

    created_detail = client.get("/api/skills/api-test-skill").json()
    assert created_detail["standard_name"] == "api-test-skill"
    assert created_detail["resources"] == []
    assert created_detail["content"].startswith("---")
    assert "name: api-test-skill" in created_detail["content"]
    assert "只用于测试" in created_detail["content"]
    resource = (
        Path(client_env.settings.skills_dir) / "api-test-skill" / "references" / "check.md"
    )
    resource.parent.mkdir(parents=True)
    resource.write_text("check", encoding="utf-8")
    assert client.get("/api/skills/api-test-skill").json()["resources"] == [
        {
            "path": "references/check.md",
            "size": resource.stat().st_size,
        }
    ]
    edited = (
        "---\nname: api-test-skill\ndescription: 接口测试技能更新\n"
        "metadata:\n  display_name: 接口测试改\n---\n\n## 要求\n更新后的正文。\n"
    )
    saved = client.put(
        "/api/skills/api-test-skill/content",
        json={"content": edited, "note": "接口测试编辑"},
    )
    assert saved.status_code == 200
    assert saved.json()["name"] == "接口测试改"
    detail_after_edit = client.get("/api/skills/api-test-skill").json()
    assert "更新后的正文" in detail_after_edit["content"]
    assert detail_after_edit["versions"][0]["note"] == "接口测试编辑"

    listed = client.get("/api/skills").json()["items"]
    listed_skill = next(item for item in listed if item["slug"] == "api-test-skill")
    assert "content" not in listed_skill
    assert "resources" not in listed_skill
    assert client.delete("/api/skills/api-test-skill").status_code == 204
    assert client.get("/api/skills/api-test-skill").status_code == 404

    toggled = client.post(
        "/api/skills/writing-style-tech-review/toggle", json={"enabled": False}
    )
    assert toggled.json()["enabled"] is False
    client.post("/api/skills/writing-style-tech-review/toggle", json={"enabled": True})

    bindings = client.get("/api/skill-bindings", params={"stage": "writing"}).json()["items"]
    assert bindings
    assert bindings[0]["skill"]["slug"]

    unbound = client.delete(f"/api/skill-bindings/{bindings[0]['id']}")
    assert unbound.status_code == 204
    created = client.post(
        "/api/skill-bindings",
        json={"stage": "writing", "slug": "writing-style-tech-review"},
    )
    assert created.status_code == 201
    assert client.get("/api/skills/missing").status_code == 404


def test_models_settings_platform_credentials(client_env):
    client = client_env.client
    models = client.get("/api/models").json()["items"]
    assert models

    created = client.post(
        "/api/models",
        json={"name": "cheap", "model": "gpt-4o-mini", "input_price_per_1k": 0.001},
    )
    assert created.status_code == 201
    model_id = created.json()["id"]
    patched = client.patch(f"/api/models/{model_id}", json={"name": "cheaper"})
    assert patched.json()["name"] == "cheaper"
    assert client.delete(f"/api/models/{model_id}").status_code == 204

    bindings = client.get("/api/model-bindings").json()["items"]
    assert len(bindings) >= 7
    binding = client.put(
        "/api/model-bindings/writing",
        json={"model_profile_id": models[0]["id"], "temperature": 0.4, "max_tokens": 2048},
    )
    assert binding.status_code == 200
    assert binding.json()["temperature"] == 0.4

    settings = client.get("/api/settings").json()["items"]
    keys = {item["key"] for item in settings}
    assert "review_pass_threshold" in keys
    assert "auto_review_advance" in keys
    from app.seed import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["auto_review_advance"] is False
    changed = client.put("/api/settings/review_pass_threshold", json={"value": 80})
    assert changed.json()["value"] == 80
    assert client.get("/api/settings/review_pass_threshold").json()["value"] == 80
    assert client.get("/api/settings/unknown").status_code == 404

    platforms = client.get("/api/platforms").json()["items"]
    assert {item["key"] for item in platforms} >= {"mock", "wechat", "zhihu", "juejin", "csdn"}
    assert client.get("/api/platforms/mock").status_code == 200

    saved = client.put(
        "/api/platforms/wechat/credentials",
        json={"payload": {"app_id": "wx-app", "app_secret": "very-secret"}},
    )
    assert saved.status_code == 200
    masked = saved.json()["masked"]
    assert masked["app_secret"].startswith("***")
    assert "very-secret" not in json.dumps(masked)
    assert client.delete("/api/platforms/wechat/credentials").status_code == 204
    assert client.get("/api/platforms/unknown").status_code == 404


def test_evolution_listing(client_env):
    client = client_env.client
    response = client.get("/api/evolution/suggestions")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert client.get("/api/evolution/suggestions/missing").status_code == 404


def test_sse_frame_and_connected_stream(client_env):
    frame = _frame({"type": "stage.status", "data": {"x": 1}})
    assert frame.startswith("event: stage.status\ndata: ")
    assert frame.endswith("\n\n")

    with client_env.client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = next(response.iter_lines())
        assert first == "event: connected"


def test_sse_heartbeat_and_disconnect_cleanup(client_env, monkeypatch):
    import asyncio

    from app.api import events as events_api
    from app.core.events import event_bus

    monkeypatch.setattr(events_api, "HEARTBEAT_SECONDS", 0.001)
    unsubscribed: list = []
    original_unsubscribe = event_bus.unsubscribe

    def tracking_unsubscribe(queue):
        unsubscribed.append(queue)
        original_unsubscribe(queue)

    monkeypatch.setattr(event_bus, "unsubscribe", tracking_unsubscribe)

    class FakeRequest:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks > 1

    async def consume():
        response = await events_api.stream_events(FakeRequest())
        iterator = response.body_iterator
        first = await iterator.__anext__()
        second = await iterator.__anext__()
        try:
            await iterator.__anext__()
        except StopAsyncIteration:
            pass
        else:
            raise AssertionError("generator should stop after disconnect")
        return first, second

    first, second = asyncio.run(consume())
    assert "event: connected" in first
    assert second == ": heartbeat\n\n"
    assert len(unsubscribed) == 1


def test_manual_sources_add_list_dedupe_and_remove(client_env, article_factory):
    article_id = article_factory()
    client = client_env.client

    created = client.post(
        f"/api/articles/{article_id}/sources",
        json={
            "title": "手动补充的来源",
            "url": "https://example.com/manual-source",
            "snippet": "人工录入的摘要",
        },
    )
    assert created.status_code == 201
    source = created.json()
    assert source["added_by"] == "user"
    assert source["title"] == "手动补充的来源"
    assert source["credibility"] in {"low", "medium", "high"}

    duplicate = client.post(
        f"/api/articles/{article_id}/sources",
        json={"title": "重复", "url": "https://example.com/manual-source/"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == source["id"]

    listed = client.get(f"/api/articles/{article_id}/sources").json()["items"]
    assert [item["id"] for item in listed] == [source["id"]]

    removed = client.delete(f"/api/articles/{article_id}/sources/{source['id']}")
    assert removed.status_code == 204
    assert client.get(f"/api/articles/{article_id}/sources").json()["items"] == []
    assert (
        client.delete(f"/api/articles/{article_id}/sources/{source['id']}").status_code
        == 404
    )

    missing = client.post(
        "/api/articles/missing/sources", json={"title": "x", "url": "https://example.com"}
    )
    assert missing.status_code == 404


def _skill_zip(slug: str = "api-zip-skill") -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{slug}/SKILL.md",
            "---\nname: api-zip-skill\ndescription: ZIP 导入测试\n"
            "metadata:\n  display_name: 压缩包技能\n---\n\n## 要求\n来自 ZIP。\n",
        )
        archive.writestr(f"{slug}/references/check.md", "check")
        archive.writestr(f"{slug}/scripts/run.py", "print(1)")
    return buffer.getvalue()


def test_skill_zip_import(client_env):
    client = client_env.client
    data = _skill_zip()

    imported = client.post(
        "/api/skills/import",
        files={"file": ("api-zip-skill.zip", data, "application/zip")},
    )
    assert imported.status_code == 201
    payload = imported.json()
    assert payload["slug"] == "api-zip-skill"
    assert payload["name"] == "压缩包技能"
    assert payload["imported_files"] == 3
    assert payload["source_filename"] == "api-zip-skill.zip"
    assert [item["path"] for item in payload["resources"]] == [
        "references/check.md",
        "scripts/run.py",
    ]
    assert payload["versions"][0]["note"] == "导入 zip：api-zip-skill.zip"
    assert "来自 ZIP" in payload["content"]

    listed = client.get("/api/skills").json()["items"]
    assert "api-zip-skill" in [item["slug"] for item in listed]
    assert client.get("/api/skills/api-zip-skill").json()["standard_name"] == "api-zip-skill"

    duplicate = client.post(
        "/api/skills/import",
        files={"file": ("again.zip", data, "application/zip")},
    )
    assert duplicate.status_code == 409

    bad_zip = client.post(
        "/api/skills/import",
        files={"file": ("bad.zip", b"not a zip", "application/zip")},
    )
    assert bad_zip.status_code == 422

    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("references/only.md", "x")
    missing = client.post(
        "/api/skills/import",
        files={"file": ("missing.zip", buffer.getvalue(), "application/zip")},
    )
    assert missing.status_code == 422

    assert client.post("/api/skills/import").status_code == 422
    removed = client.delete("/api/skills/api-zip-skill")
    assert removed.status_code == 204, removed.text


def test_skill_zip_export_round_trips(client_env):
    import io
    import zipfile

    client = client_env.client
    response = client.get("/api/skills/writing-style-tech-review/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert (
        'filename="writing-style-tech-review.zip"'
        in response.headers["content-disposition"]
    )

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "writing-style-tech-review/SKILL.md" in names
        assert all(name.startswith("writing-style-tech-review/") for name in names)
        assert archive.read("writing-style-tech-review/SKILL.md").startswith(b"---")

    imported = client.post(
        "/api/skills/import",
        data={"slug": "export-copy"},
        files={
            "file": (
                "writing-style-tech-review.zip",
                response.content,
                "application/zip",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["slug"] == "export-copy"
    assert client.get("/api/skills/export-copy").json()["status"] == "valid"
    assert client.delete("/api/skills/export-copy").status_code == 204

    assert client.get("/api/skills/missing/export").status_code == 404


def test_review_stage_returns_latest_human_decision(client_env, article_factory):
    article_id = article_factory(platforms=["mock"])
    client = client_env.client
    run = client.post(f"/api/articles/{article_id}/run").json()
    client_env.runner.execute_sync(run["id"], initial=True)

    with client_env.session_factory() as session:
        report = session.scalar(
            select(ReviewReport)
            .where(ReviewReport.article_id == article_id)
            .order_by(ReviewReport.created_at.desc())
        )
        assert report is not None
        session.add(
            ReviewDecision(
                article_id=article_id,
                run_id=run["id"],
                report_id=report.id,
                decision="rejected",
                feedback="结构需要调整",
                rollback_to=Stage.OUTLINE,
                target_reason="意见指向结构问题",
            )
        )
        session.commit()

    content = client.get(f"/api/articles/{article_id}/stages/review").json()["content"]
    decision = content["latest_decision"]
    assert decision["decision"] == "rejected"
    assert decision["feedback"] == "结构需要调整"
    assert decision["rollback_to"] == Stage.OUTLINE
    assert decision["target_reason"] == "意见指向结构问题"
    assert decision["created_at"]


def test_review_decision_api_validates_state_and_feedback(client_env, article_factory):
    client = client_env.client
    article_id = article_factory(platforms=["mock"])

    conflict = client.post(
        f"/api/articles/{article_id}/review/decision", json={"decision": "approve"}
    )
    assert conflict.status_code == 409

    client.put("/api/settings/auto_review_advance", json={"value": False})
    run = client.post(f"/api/articles/{article_id}/run").json()
    client_env.runner.execute_sync(run["id"], initial=True)
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "waiting_review"

    empty_feedback = client.post(
        f"/api/articles/{article_id}/review/decision",
        json={"decision": "reject", "feedback": "   "},
    )
    assert empty_feedback.status_code == 422
    assert client.get(f"/api/runs/{run['id']}").json()["status"] == "waiting_review"

    approved = client.post(
        f"/api/articles/{article_id}/review/decision", json={"decision": "approve"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "running"
