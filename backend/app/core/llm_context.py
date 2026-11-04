"""Context variables used to attribute LLM calls to articles and stages.

Values passed as ``None`` leave the existing context untouched, so nested
calls (for example an LLM service inside a workflow node) keep the outer
run/stage attribution.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

current_article_id: ContextVar[str | None] = ContextVar("current_article_id", default=None)
current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
current_stage: ContextVar[str | None] = ContextVar("current_stage", default=None)


@contextmanager
def llm_context(
    *,
    article_id: str | None = None,
    run_id: str | None = None,
    stage: str | None = None,
) -> Iterator[None]:
    tokens: list[tuple[ContextVar, Token]] = []
    if article_id is not None:
        tokens.append((current_article_id, current_article_id.set(article_id)))
    if run_id is not None:
        tokens.append((current_run_id, current_run_id.set(run_id)))
    if stage is not None:
        tokens.append((current_stage, current_stage.set(stage)))
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)
