"""Step / timeout / token budget wrapper for deep agents."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.analytics.cost import extract_usage
from app.core.errors import BudgetExceededError

logger = logging.getLogger(__name__)


class TokenBudget:
    """Thread-safe accounting shared between callbacks and the caller."""

    def __init__(self, max_tokens: int, max_steps: int) -> None:
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.steps = 0
        self.started_at = time.perf_counter()
        self._lock = threading.Lock()

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add_usage(self, prompt: int, completion: int) -> None:
        with self._lock:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            if self.total_tokens > self.max_tokens:
                raise BudgetExceededError(
                    f"deep agent Token 预算超限：{self.total_tokens}/{self.max_tokens}",
                    details=self.as_dict(),
                )

    def add_step(self) -> None:
        with self._lock:
            self.steps += 1
            if self.steps > self.max_steps:
                raise BudgetExceededError(
                    f"deep agent 步数超限：{self.steps}/{self.max_steps}",
                    details=self.as_dict(),
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "steps": self.steps,
            "elapsed_seconds": round(time.perf_counter() - self.started_at, 3),
        }


class BudgetCallback(BaseCallbackHandler):
    def __init__(self, budget: TokenBudget, cancel_event: Any = None) -> None:
        self.budget = budget
        self.cancel_event = cancel_event

    def _stop(self) -> None:
        # LangChain swallows callback exceptions, so also signal cooperative
        # cancellation; tools check the event before doing network work.
        if self.cancel_event is not None:
            self.cancel_event.set()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = extract_usage(response)
        if usage is not None:
            try:
                self.budget.add_usage(*usage)
            except BudgetExceededError:
                self._stop()
                raise

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        try:
            self.budget.add_step()
        except BudgetExceededError:
            self._stop()
            raise


def run_with_budget(
    agent: Any,
    payload: Any,
    *,
    config: dict[str, Any] | None = None,
    max_steps: int = 8,
    timeout_seconds: float = 120.0,
    max_tokens: int = 30_000,
    cancel_event: Any = None,
) -> Any:
    """Invoke a deep agent while enforcing step, wall-clock and token limits."""
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    budget = TokenBudget(max_tokens=max_tokens, max_steps=max_steps)
    callback = BudgetCallback(budget, cancel_event=cancel_event)
    merged = dict(config or {})
    merged["recursion_limit"] = min(
        int(merged.get("recursion_limit", max_steps * 2 + 2)), max_steps * 2 + 2
    )
    merged["callbacks"] = [*merged.get("callbacks", []), callback]

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deep-agent")
    # ThreadPoolExecutor does not copy contextvars; do it explicitly so spans
    # opened by tools inside the agent stay attached to the current workflow.
    context = contextvars.copy_context()
    future = executor.submit(context.run, agent.invoke, payload, merged)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        # A running thread cannot be killed; signal tools to stop doing work.
        if cancel_event is not None:
            cancel_event.set()
        future.cancel()
        raise BudgetExceededError(
            f"deep agent 执行超时（{timeout_seconds}s）", details=budget.as_dict()
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
