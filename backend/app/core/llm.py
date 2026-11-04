"""OpenAI-compatible model factory and structured-output helper."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, TypeVar, get_origin

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.cost import CostTracker
from app.core.config import Settings, get_settings
from app.core.errors import LLMConfigError, StructuredOutputError
from app.core.llm_context import (
    current_article_id,
    current_run_id,
    current_stage,
    llm_context,
)
from app.core.tracing import get_langfuse_handler
from app.models.llm import ModelProfile, StageModelBinding

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

ModelFactory = Callable[[str], Any]


def _message_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def parse_json_payload(text: str) -> Any:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _validate_model_payload(schema: type[T], payload: Any) -> T:
    """Accept a bare list only for a schema with one list-valued field."""
    if isinstance(payload, list) and len(schema.model_fields) == 1:
        field_name, field = next(iter(schema.model_fields.items()))
        if get_origin(field.annotation) is list:
            payload = {field_name: payload}
    return schema.model_validate(payload)


class LLMService:
    """Resolves the stage model and performs structured or plain calls."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        settings: Settings | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.model_factory = model_factory

    def get_binding(self, stage: str) -> tuple[StageModelBinding, ModelProfile]:
        with self.session_factory() as session:
            binding = session.scalar(
                select(StageModelBinding).where(StageModelBinding.stage == stage)
            )
            if binding is None:
                raise LLMConfigError(f"阶段 {stage} 尚未绑定模型")
            profile = session.get(ModelProfile, binding.model_profile_id)
            if profile is None:
                raise LLMConfigError(f"阶段 {stage} 绑定的模型档案不存在")
            session.expunge(binding)
            session.expunge(profile)
            return binding, profile

    def build_model(self, stage: str, *, timeout_seconds: float | None = None) -> Any:
        if self.model_factory is not None:
            return self.model_factory(stage)
        binding, profile = self.get_binding(stage)
        api_key = os.environ.get(profile.api_key_env) or self.settings.llm_api_key
        if not api_key:
            raise LLMConfigError(
                f"模型 {profile.name} 缺少 API Key，请设置 {profile.api_key_env} 或 APP_LLM_API_KEY"
            )
        from langchain_openai import ChatOpenAI

        callbacks: list[Any] = [
            CostTracker(self.session_factory, profile.model, profile.provider)
        ]
        handler = get_langfuse_handler()
        if handler is not None:
            callbacks.append(handler)
        return ChatOpenAI(
            model=profile.model,
            base_url=profile.base_url or self.settings.llm_base_url,
            api_key=api_key,
            temperature=binding.temperature,
            max_tokens=binding.max_tokens,
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else self.settings.llm_timeout_seconds
            ),
            # A deadline must bound the whole call, not each retry attempt.
            max_retries=(
                0 if timeout_seconds is not None else self.settings.llm_max_retries
            ),
            callbacks=callbacks,
        )

    @staticmethod
    def _invoke(runnable: Any, messages: list[Any], config: dict[str, Any] | None) -> Any:
        if config is None:
            return runnable.invoke(messages)
        return runnable.invoke(messages, config=config)

    @staticmethod
    def _trace_config(
        stage: str, article_id: str | None, run_id: str | None
    ) -> dict[str, Any] | None:
        """Attach stage metadata when tracing is active; ``None`` otherwise."""
        if get_langfuse_handler() is None:
            return None
        article = article_id or current_article_id.get()
        run = run_id or current_run_id.get()
        metadata: dict[str, Any] = {"stage": stage or current_stage.get()}
        if article:
            metadata["article_id"] = article
        if run:
            metadata["run_id"] = run
            metadata["langfuse_session_id"] = run
        metadata["langfuse_tags"] = [metadata["stage"]]
        return {"metadata": metadata}

    def structured(
        self,
        *,
        stage: str,
        schema: type[T],
        system: str,
        user: str,
        article_id: str | None = None,
        run_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> T:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None

        def next_model() -> Any:
            """Build a model whose SDK timeout never exceeds the remaining budget."""
            if deadline is None:
                return self.build_model(stage)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StructuredOutputError(
                    f"模型结构化输出超时（阶段 {stage}）：{timeout_seconds}s"
                )
            return self.build_model(stage, timeout_seconds=remaining)

        with llm_context(article_id=article_id, run_id=run_id, stage=stage):
            model = next_model()
            messages = self._messages(system, user)
            trace_config = self._trace_config(stage, article_id, run_id)
            first_error: Exception | None = None
            structured_model = None
            try:
                structured_model = model.with_structured_output(schema)
            except (AttributeError, NotImplementedError):
                structured_model = None
            if structured_model is not None:
                try:
                    result = self._invoke(structured_model, messages, trace_config)
                    if isinstance(result, schema):
                        return result
                    if isinstance(result, (dict, list)):
                        return _validate_model_payload(schema, result)
                    raise ValueError(f"unexpected structured result type: {type(result)!r}")
                except Exception as exc:  # noqa: BLE001 - fall back to JSON mode
                    first_error = exc
                    logger.warning("structured output failed, falling back to JSON mode: %s", exc)

            json_user = (
                f"{user}\n\n请只输出一个 JSON 对象，不要输出解释或 Markdown 代码块。"
                f"JSON 必须符合以下 schema：\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
            )
            try:
                response = self._invoke(
                    next_model(), self._messages(system, json_user), trace_config
                )
                return _validate_model_payload(schema, parse_json_payload(_message_content(response)))
            except Exception as exc:  # noqa: BLE001
                # Keep the original task in the repair turn: a schema-only retry
                # makes the model answer without the article it was reviewing.
                repair_user = (
                    f"{user}\n\n---\n"
                    f"上一次输出无法通过校验：{exc}。请基于以上全部内容修正后只输出 JSON 对象。\n"
                    f"要求 schema：\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                )
                try:
                    response = self._invoke(
                        next_model(), self._messages(system, repair_user), trace_config
                    )
                    return _validate_model_payload(schema, parse_json_payload(_message_content(response)))
                except Exception as repair_exc:  # noqa: BLE001
                    raise StructuredOutputError(
                        f"模型结构化输出失败（阶段 {stage}）：{repair_exc}",
                        details={"first_error": str(first_error) if first_error else None},
                    ) from repair_exc

    def text(
        self,
        *,
        stage: str,
        system: str,
        user: str,
        article_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        with llm_context(article_id=article_id, run_id=run_id, stage=stage):
            model = self.build_model(stage)
            response = self._invoke(
                model,
                self._messages(system, user),
                self._trace_config(stage, article_id, run_id),
            )
            return _message_content(response)

    @staticmethod
    def _messages(system: str, user: str) -> list[Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        return [SystemMessage(content=system), HumanMessage(content=user)]


def validate_schema_output(schema: type[T], payload: Any) -> T:
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(f"输出不符合 schema: {exc}") from exc
