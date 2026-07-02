"""Typed LLM provider errors and normalized error codes.

Invalid or empty model output must never be silently treated as a successful
assessment. Providers raise :class:`LLMProviderError` with a specific
``error_code`` so callers can fail closed or downgrade to manual review.

Safety: the exception string intentionally excludes the model name, prompts, and
raw provider bodies so failures cannot leak private trade prompts or secrets into
logs. Only the error code, provider name, and a coarse detail tag are exposed.
"""
from __future__ import annotations

# Normalized error codes.
LLM_EMPTY_RESPONSE = "LLM_EMPTY_RESPONSE"
LLM_INVALID_JSON = "LLM_INVALID_JSON"
LLM_SCHEMA_VALIDATION_FAILED = "LLM_SCHEMA_VALIDATION_FAILED"
LLM_PROVIDER_TIMEOUT = "LLM_PROVIDER_TIMEOUT"
LLM_PROVIDER_CONNECTION_ERROR = "LLM_PROVIDER_CONNECTION_ERROR"
LLM_PROVIDER_UNSUPPORTED_RESPONSE = "LLM_PROVIDER_UNSUPPORTED_RESPONSE"

# Codes that are safe to retry (transient / possibly-transient conditions).
RETRYABLE_CODES = frozenset(
    {LLM_EMPTY_RESPONSE, LLM_PROVIDER_TIMEOUT, LLM_PROVIDER_CONNECTION_ERROR}
)


class LLMProviderError(RuntimeError):
    """A controlled LLM provider failure.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` / ``except
    Exception`` call sites keep working while gaining a typed ``error_code``.
    """

    def __init__(
        self,
        error_code: str,
        provider: str = "",
        model: str = "",
        retryable: bool | None = None,
        manual_review_required: bool = True,
        detail: str = "",
    ):
        self.error_code = error_code
        self.provider = provider
        # Stored for the structured assessment, deliberately NOT in the message.
        self.model = model
        self.retryable = error_code in RETRYABLE_CODES if retryable is None else retryable
        self.manual_review_required = manual_review_required
        # ``detail`` must be a short, non-sensitive tag (e.g. an exception class
        # name), never a prompt or provider body.
        self.detail = detail
        message = f"{error_code} from provider '{provider or 'unknown'}'"
        if detail:
            message += f" ({detail})"
        super().__init__(message)

    def to_manual_review_assessment(self) -> dict:
        """Normalized, safe-to-serialize failure payload for manual review."""
        return {
            "ok": False,
            "error_code": self.error_code,
            "provider": self.provider,
            "model": self.model,
            "manual_review_required": self.manual_review_required,
            "retryable": self.retryable,
        }
