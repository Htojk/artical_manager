"""Domain errors mapped to HTTP responses by the API layer."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "app_error"
    status_code = 400

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    status_code = 413


class ValidationError(AppError):
    code = "validation_error"
    status_code = 422


class CredentialError(AppError):
    code = "credential_missing"
    status_code = 422


class LLMConfigError(AppError):
    code = "llm_not_configured"
    status_code = 422


class StructuredOutputError(AppError):
    code = "structured_output_failed"
    status_code = 502


class AdapterError(AppError):
    code = "adapter_error"
    status_code = 502


class ManualPublishRequired(AppError):
    code = "manual_publish_required"
    status_code = 409


class BudgetExceededError(AppError):
    code = "budget_exceeded"
    status_code = 504
