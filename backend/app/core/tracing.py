"""Optional self-hosted Langfuse tracing.

Tracing is disabled unless ``APP_LANGFUSE_ENABLED`` is true and the host,
public key and secret key are all configured. Every entry point degrades to a
no-op or logs a warning, so a missing or unreachable tracing backend can never
change workflow behaviour.
"""

from __future__ import annotations

import logging
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import Settings

logger = logging.getLogger(__name__)

_ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

_client: Any = None
_handler: Any = None


def _clean_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    cleaned = {key: value for key, value in metadata.items() if value is not None}
    return cleaned or None


def _environment(settings: Settings) -> str | None:
    value = (settings.env or "").strip().lower()
    if value.startswith("langfuse") or not _ENVIRONMENT_PATTERN.fullmatch(value):
        return None
    return value


def configure_tracing(settings: Settings) -> bool:
    """Initialise tracing when explicitly enabled.

    Returns whether tracing is active. Initialisation failures are logged and
    swallowed so the application can always start.
    """
    global _client, _handler

    _client = None
    _handler = None
    if not settings.langfuse_enabled:
        return False

    missing = [
        name
        for name, value in (
            ("APP_LANGFUSE_HOST", settings.langfuse_host),
            ("APP_LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key),
            ("APP_LANGFUSE_SECRET_KEY", settings.langfuse_secret_key),
        )
        if not (value or "").strip()
    ]
    if missing:
        logger.warning(
            "Langfuse tracing disabled; missing configuration: %s",
            ", ".join(missing),
        )
        return False

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        client = Langfuse(
            public_key=settings.langfuse_public_key.strip(),
            secret_key=settings.langfuse_secret_key.strip(),
            host=settings.langfuse_host.strip(),
            timeout=int(round(settings.langfuse_timeout_seconds)),
            sample_rate=settings.langfuse_sample_rate,
            environment=_environment(settings),
        )
        handler = CallbackHandler()
    except Exception:  # noqa: BLE001 - tracing must never block startup
        logger.warning(
            "Langfuse tracing initialisation failed; continuing without tracing",
            exc_info=True,
        )
        return False

    _client = client
    _handler = handler
    logger.info("Langfuse tracing enabled (host=%s)", settings.langfuse_host.strip())
    return True


def tracing_enabled() -> bool:
    return _client is not None


def get_langfuse_client() -> Any:
    return _client


def get_langfuse_handler() -> Any:
    return _handler


@contextmanager
def trace_attributes(
    *,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    trace_name: str | None = None,
) -> Iterator[None]:
    """Propagate trace-level attributes to every span created in the context."""
    client = _client
    if client is None:
        yield
        return
    try:
        from langfuse import propagate_attributes

        manager = propagate_attributes(
            session_id=session_id,
            metadata=_clean_metadata(metadata),
            tags=tags,
            trace_name=trace_name,
        )
    except Exception:  # noqa: BLE001 - tracing must never break the caller
        logger.warning("failed to propagate trace attributes", exc_info=True)
        yield
        return
    with manager:
        yield


@contextmanager
def trace_span(
    name: str,
    *,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
    as_type: str = "span",
) -> Iterator[Any]:
    """Open a span, yielding ``None`` when tracing is disabled.

    Errors raised by the caller propagate normally; only tracing setup failures
    are swallowed so business code keeps running.
    """
    client = _client
    if client is None:
        yield None
        return
    try:
        manager = client.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=input,
            metadata=_clean_metadata(metadata),
        )
    except Exception:  # noqa: BLE001 - tracing must never break the caller
        logger.warning("failed to start trace span %s", name, exc_info=True)
        yield None
        return
    with manager as span:
        try:
            yield span
        except Exception as exc:
            try:
                span.update(level="ERROR", status_message=str(exc))
            except Exception:  # noqa: BLE001 - never mask the caller's error
                logger.debug("failed to mark trace span as failed", exc_info=True)
            raise


def shutdown_tracing(timeout: float | None = None) -> None:
    """Flush and close the tracing client, bounded by ``timeout`` seconds."""
    global _client, _handler

    client = _client
    _client = None
    _handler = None
    if client is None:
        return

    limit = 5.0 if timeout is None else timeout
    finished = threading.Event()

    def _close() -> None:
        try:
            client.shutdown()
        except Exception:  # noqa: BLE001 - shutdown must never raise
            logger.warning("Langfuse shutdown failed", exc_info=True)
        finally:
            finished.set()

    thread = threading.Thread(target=_close, name="langfuse-shutdown", daemon=True)
    thread.start()
    if not finished.wait(limit):
        logger.warning("Langfuse shutdown exceeded %.1fs; continuing", limit)
