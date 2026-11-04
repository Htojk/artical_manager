"""LLM usage accounting: extract tokens, price them and persist a ledger row."""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.llm_context import current_article_id, current_run_id, current_stage
from app.models.llm import LLMCall, ModelProfile

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_usage(response: Any) -> tuple[int, int] | None:
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if token_usage:
        prompt = token_usage.get("prompt_tokens", token_usage.get("input_tokens"))
        completion = token_usage.get("completion_tokens", token_usage.get("output_tokens"))
        if prompt is not None or completion is not None:
            return _as_int(prompt), _as_int(completion)

    generations = getattr(response, "generations", None) or []
    if generations and generations[0]:
        message = getattr(generations[0][0], "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        if usage:
            return _as_int(usage.get("input_tokens")), _as_int(usage.get("output_tokens"))
        response_metadata = getattr(message, "response_metadata", None) or {}
        usage = response_metadata.get("token_usage") or {}
        if usage:
            return _as_int(usage.get("prompt_tokens")), _as_int(usage.get("completion_tokens"))
    return None


def _collect_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_collect_text(item) for item in value)
    content = getattr(value, "content", None)
    if content is not None:
        return _collect_text(content)
    return str(value)


def extract_completion_text(response: Any) -> str:
    generations = getattr(response, "generations", None) or []
    if not generations or not generations[0]:
        return ""
    generation = generations[0][0]
    text = getattr(generation, "text", None)
    if text:
        return str(text)
    return _collect_text(getattr(generation, "message", ""))


def estimate_tokens(prompts: Any, completion: str) -> tuple[int, int]:
    try:
        import tiktoken

        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001
            encoding = tiktoken.encoding_for_model("gpt-4o")
    except Exception:  # noqa: BLE001
        prompt_text = _collect_text(prompts)
        return max(1, len(prompt_text) // 4), max(1, len(completion) // 4)
    prompt_text = _collect_text(prompts)
    return len(encoding.encode(prompt_text)), len(encoding.encode(completion))


def lookup_prices(session: Session, model: str) -> tuple[float | None, float | None, str]:
    profile = session.scalar(
        select(ModelProfile)
        .where(ModelProfile.model == model)
        .order_by(ModelProfile.updated_at.desc())
    )
    if profile is None:
        return None, None, "CNY"
    return profile.input_price_per_1k, profile.output_price_per_1k, profile.currency


def compute_cost(prompt_tokens: int, completion_tokens: int, input_price: float | None, output_price: float | None) -> float | None:
    if input_price is None or output_price is None:
        return None
    return round(
        (prompt_tokens / 1000.0) * input_price + (completion_tokens / 1000.0) * output_price,
        6,
    )


def record_llm_call(
    session: Session,
    *,
    model: str,
    provider: str = "openai-compatible",
    stage: str | None = None,
    article_id: str | None = None,
    run_id: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    input_price: float | None = None,
    output_price: float | None = None,
    currency: str = "CNY",
    latency_ms: int = 0,
    status: str = "success",
    estimated: bool = False,
    error: str | None = None,
) -> LLMCall:
    if input_price is None and output_price is None:
        input_price, output_price, currency = lookup_prices(session, model)
    price_missing = input_price is None or output_price is None
    cost = None if price_missing else compute_cost(prompt_tokens, completion_tokens, input_price, output_price)
    call = LLMCall(
        article_id=article_id,
        run_id=run_id,
        stage=stage or current_stage.get() or "unknown",
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_price_per_1k=input_price,
        output_price_per_1k=output_price,
        cost=cost,
        currency=currency,
        latency_ms=latency_ms,
        status=status,
        estimated=estimated,
        price_missing=price_missing,
        error=error,
    )
    session.add(call)
    session.commit()
    return call


class CostTracker(BaseCallbackHandler):
    """LangChain callback that writes every real model call to the ledger."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        model: str,
        provider: str = "openai-compatible",
    ) -> None:
        self.session_factory = session_factory
        self.model = model
        self.provider = provider

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        self._started = time.perf_counter()

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        latency = int((time.perf_counter() - getattr(self, "_started", time.perf_counter())) * 1000)
        try:
            with self.session_factory() as session:
                record_llm_call(
                    session,
                    model=self.model,
                    provider=self.provider,
                    article_id=current_article_id.get(),
                    run_id=current_run_id.get(),
                    stage=current_stage.get(),
                    latency_ms=latency,
                    status="error",
                    error=str(error)[:2000],
                )
        except Exception:  # noqa: BLE001 - accounting must never break the call
            logger.exception("failed to record failed llm call")

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        latency = int((time.perf_counter() - getattr(self, "_started", time.perf_counter())) * 1000)
        usage = extract_usage(response)
        estimated = False
        if usage is None:
            prompts = kwargs.get("prompts") or []
            completion = extract_completion_text(response)
            usage = estimate_tokens(prompts, completion)
            estimated = True
        prompt_tokens, completion_tokens = usage
        try:
            with self.session_factory() as session:
                record_llm_call(
                    session,
                    model=self.model,
                    provider=self.provider,
                    article_id=current_article_id.get(),
                    run_id=current_run_id.get(),
                    stage=current_stage.get(),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency,
                    estimated=estimated,
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to record llm call")
