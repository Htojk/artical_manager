"""Structured logging with request ids and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-\.]{6,})", re.IGNORECASE),
    re.compile(r"(authorization\"?\s*[:=]\s*\"?Bearer\s+)([A-Za-z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"(cookie\"?\s*[:=]\s*\"?)([^\"\s,]{6,})", re.IGNORECASE),
    re.compile(r"(access[_-]?token\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-\.]{6,})", re.IGNORECASE),
    re.compile(r"(app[_-]?secret\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-\.]{6,})", re.IGNORECASE),
]


def redact(value: Any) -> Any:
    """Recursively mask values that look like credentials."""
    if isinstance(value, str):
        output = value
        for pattern in _SECRET_PATTERNS:
            output = pattern.sub(lambda m: f"{m.group(1)}***", output)
        return output
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact(item) for item in value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        extra = getattr(record, "extra_data", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = redact(record.getMessage())
        return f"{self.formatTime(record)} [{request_id_var.get()}] {record.levelname} {record.name}: {message}"


def configure_logging(level: str = "INFO", *, log_dir: Path | None = None, json_logs: bool | None = None) -> None:
    if json_logs is None:
        json_logs = False
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    formatter: logging.Formatter = JsonFormatter() if json_logs else PlainFormatter()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "backend.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def set_request_id(value: str) -> None:
    request_id_var.set(value or "-")
