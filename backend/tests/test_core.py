"""Core infrastructure: database, prompts, events, security, LLM helper."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.db import (
    configure_engine,
    get_session_factory,
    init_db,
    reset_engine,
    session_scope,
)
from app.core.errors import LLMConfigError, StructuredOutputError
from app.core.events import Event, EventBus
from app.core.llm import LLMService, parse_json_payload, validate_schema_output
from app.core.prompts import PromptLoader, PromptRenderError
from app.core.security import CredentialCipher, CredentialService, mask_secret
from app.models.system import Credential


@pytest.fixture
def settings(test_settings):
    return test_settings


def test_database_roundtrip_and_wal(settings):
    configure_engine(settings=settings)
    init_db()
    factory = get_session_factory()
    with factory() as session:
        session.add(Credential(platform="demo", encrypted_payload="x"))
        session.commit()
    with factory() as session:
        assert session.query(Credential).count() == 1
        assert session.connection().exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_session_scope_rolls_back(settings):
    configure_engine(settings=settings)
    init_db()
    with pytest.raises(RuntimeError):
        with session_scope() as session:
            session.add(Credential(platform="bad", encrypted_payload="y"))
            raise RuntimeError("boom")
    with get_session_factory()() as session:
        assert session.query(Credential).filter_by(platform="bad").first() is None
    reset_engine()


def test_prompt_rendering(tmp_path):
    (tmp_path / "demo.md").write_text("你好 {{ who }}", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    assert loader.render("demo.md", who="世界") == "你好 世界"


def test_prompt_missing_variable_and_template(tmp_path):
    (tmp_path / "demo.md").write_text("你好 {{ who }}", encoding="utf-8")
    loader = PromptLoader(tmp_path)
    with pytest.raises(PromptRenderError):
        loader.render("demo.md")
    with pytest.raises(PromptRenderError):
        loader.render("missing.md")


def test_parse_json_variants():
    assert parse_json_payload('{"a": 1}') == {"a": 1}
    assert parse_json_payload("```json\n{\"a\": 2}\n```") == {"a": 2}
    assert parse_json_payload('前缀 {"a": 3} 后缀') == {"a": 3}
    with pytest.raises(Exception):
        parse_json_payload("not json")


def test_event_bus_pubsub():
    bus = EventBus()
    queue = bus.subscribe()
    assert bus.subscriber_count() == 1
    bus.publish(Event(type="stage.status", article_id="a", data={"x": 1}))
    event = queue.get_nowait()
    assert event.type == "stage.status"
    assert event.data == {"x": 1}
    bus.unsubscribe(queue)
    assert bus.subscriber_count() == 0


@pytest.mark.asyncio
async def test_event_bus_loop_dispatch():
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    queue = bus.subscribe()
    bus.publish(Event(type="run.status"))
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event.type == "run.status"


def test_credential_cipher_roundtrip(settings):
    cipher = CredentialCipher(settings)
    token = cipher.encrypt({"app_id": "wx123", "app_secret": "secret"})
    assert "wx123" not in token
    assert cipher.decrypt(token) == {"app_id": "wx123", "app_secret": "secret"}


def test_credential_cipher_auto_key(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        secret_key=None,
    )
    cipher = CredentialCipher(settings)
    token = cipher.encrypt({"a": "b"})
    assert (tmp_path / "secret.key").exists()
    assert cipher.decrypt(token) == {"a": "b"}


def test_credential_service(settings, db_session):
    service = CredentialService(db_session, CredentialCipher(settings))
    service.set("wechat", {"app_id": "wx-app", "app_secret": "very-secret", "publish_mode": "draft",
                           "cover_media_ids": {"entertainment": "cover-one"}})
    assert service.get("wechat")["app_id"] == "wx-app"
    service.set("wechat", {"app_id": "wx-app", "app_secret": "new-secret", "publish_mode": "draft"})
    assert service.get("wechat")["cover_media_ids"] == {"entertainment": "cover-one"}
    masked = service.masked("wechat")
    assert masked["app_secret"].startswith("***")
    assert masked["cover_media_ids"] == {"entertainment": "***-one"}
    assert masked["publish_mode"] == "draft"
    assert "very-secret" not in str(masked)
    service.delete("wechat")
    assert service.get("wechat") == {}


def test_mask_secret():
    assert mask_secret(None) == ""
    assert mask_secret("abc") == "***"
    assert mask_secret("abcdef") == "***cdef"


class _Out(BaseModel):
    title: str
    count: int = Field(default=0)


class _Structured:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def invoke(self, _messages):
        if self.error:
            raise self.error
        return self.result


class _Model:
    def __init__(self, *, structured=None, responses=None):
        self.structured = structured
        self.responses = list(responses or [])
        self.calls = 0

    def with_structured_output(self, _schema):
        if isinstance(self.structured, Exception):
            raise self.structured
        return self.structured

    def invoke(self, _messages):
        self.calls += 1

        class Response:
            content = self.responses.pop(0)

        return Response()


def _llm(settings, model):
    return LLMService(
        get_session_factory(), settings=settings, model_factory=lambda stage: model
    )


def test_llm_structured_happy(settings):
    configure_engine(settings=settings)
    init_db()
    model = _Model(structured=_Structured(_Out(title="ok")))
    result = _llm(settings, model).structured(
        stage="writing", schema=_Out, system="s", user="u"
    )
    assert result.title == "ok"


def test_llm_structured_falls_back_to_json(settings):
    configure_engine(settings=settings)
    init_db()
    model = _Model(
        structured=NotImplementedError("unsupported"), responses=['{"title": "json"}']
    )
    result = _llm(settings, model).structured(
        stage="writing", schema=_Out, system="s", user="u"
    )
    assert result.title == "json"


def test_topic_structured_accepts_bare_candidate_list(settings):
    """Some compatible providers return the sole list field without its wrapper."""
    from app.core.constants import Stage
    from app.schemas.artifacts import TopicCandidates

    configure_engine(settings=settings)
    init_db()
    candidates = [
        {"title": f"第{i}个可写候选", "angle": "一个真实角度", "rationale": "一个真实理由"}
        for i in range(5)
    ]
    model = _Model(structured=_Structured(candidates))
    result = _llm(settings, model).structured(
        stage=Stage.TOPIC, schema=TopicCandidates, system="选题", user="给我五个选题"
    )
    assert len(result.candidates) == 5
    assert model.calls == 0


def test_topic_json_fallback_accepts_bare_candidate_list(settings):
    from app.core.constants import Stage
    from app.schemas.artifacts import TopicCandidates

    configure_engine(settings=settings)
    init_db()
    candidates = [
        {"title": f"第{i}个可写候选", "angle": "一个真实角度", "rationale": "一个真实理由"}
        for i in range(5)
    ]
    model = _Model(
        structured=NotImplementedError("unsupported"),
        responses=[json.dumps(candidates, ensure_ascii=False)],
    )
    result = _llm(settings, model).structured(
        stage=Stage.TOPIC, schema=TopicCandidates, system="选题", user="给我五个选题"
    )
    assert len(result.candidates) == 5
    assert model.calls == 1


def test_llm_structured_repairs_once(settings):
    configure_engine(settings=settings)
    init_db()
    model = _Model(
        structured=NotImplementedError("unsupported"),
        responses=["not-json", '{"title": "fixed"}'],
    )
    result = _llm(settings, model).structured(
        stage="writing", schema=_Out, system="s", user="u"
    )
    assert result.title == "fixed"


def test_llm_structured_fails_after_repair(settings):
    configure_engine(settings=settings)
    init_db()
    model = _Model(structured=NotImplementedError("unsupported"), responses=["no", "still no"])
    with pytest.raises(StructuredOutputError):
        _llm(settings, model).structured(stage="writing", schema=_Out, system="s", user="u")


def test_topic_structured_output_has_room_for_five_candidates(settings):
    """A five-candidate response must not be forced through the old 4096-token cap."""
    from sqlalchemy import select

    from app.core.constants import Stage
    from app.models.llm import StageModelBinding
    from app.schemas.artifacts import TopicCandidates
    from app.seed import seed_defaults

    configure_engine(settings=settings)
    init_db()
    factory = get_session_factory()
    with factory() as session:
        seed_defaults(session, settings=settings)

    broken = '{"candidates": [{"title": "第一候选", "angle": "一个真实角度", "rationale": "一个真实理由"} {"title": "第二候选"}]}'
    valid = {"candidates": [
        {"title": f"第{i}个可写候选", "angle": "一个真实角度", "rationale": "一个真实理由"}
        for i in range(5)
    ]}

    class BudgetModel:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            with factory() as session:
                budget = session.scalar(
                    select(StageModelBinding.max_tokens).where(StageModelBinding.stage == Stage.TOPIC)
                )
            if budget < 8192:
                return type("Response", (), {"content": broken})()
            return valid

    llm = LLMService(factory, settings=settings, model_factory=lambda _stage: BudgetModel())
    output = llm.structured(stage=Stage.TOPIC, schema=TopicCandidates, system="选题", user="给我五个选题")
    assert len(output.candidates) == 5


def test_llm_structured_timeout_skips_repair_after_deadline(settings):
    configure_engine(settings=settings)
    init_db()
    calls = 0

    class SlowModel:
        def with_structured_output(self, _schema):
            raise NotImplementedError("unsupported")

        def invoke(self, _messages):
            nonlocal calls
            calls += 1
            time.sleep(0.1)

            class Response:
                content = "not-json"

            return Response()

    started = time.monotonic()
    with pytest.raises(StructuredOutputError, match="模型结构化输出失败"):
        _llm(settings, SlowModel()).structured(
            stage="writing", schema=_Out, system="s", user="u", timeout_seconds=0.05
        )
    assert calls == 1
    assert time.monotonic() - started < 0.5


def test_llm_text(settings):
    configure_engine(settings=settings)
    init_db()
    model = _Model(responses=["plain text"])
    assert _llm(settings, model).text(stage="writing", system="s", user="u") == "plain text"


def test_llm_missing_binding(settings):
    configure_engine(settings=settings)
    init_db()
    service = LLMService(get_session_factory(), settings=settings)
    with pytest.raises(LLMConfigError):
        service.build_model("writing")


def test_validate_schema_output():
    assert validate_schema_output(_Out, {"title": "x"}).title == "x"
    with pytest.raises(StructuredOutputError):
        validate_schema_output(_Out, {"count": 1})
