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

# Token-Guard specific codes.
LLM_CONTEXT_OVERFLOW = "LLM_CONTEXT_OVERFLOW"
LLM_BUSY = "LLM_BUSY"
LLM_ABORTED = "LLM_ABORTED"

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


class LlmContextOverflowError(LLMProviderError):
    """Estimated prompt + output budget exceeds the context window.

    Raised *before* any network request so an over-long prompt never reaches
    Ollama. Carries the estimate so the business layer can decide how to
    compress its input; the guard never silently truncates the prompt.
    """

    def __init__(self, est_prompt_tokens: int, num_predict: int, context_window: int,
                 provider: str = "", model: str = ""):
        self.est_prompt_tokens = est_prompt_tokens
        self.num_predict = num_predict
        self.context_window = context_window
        detail = f"est_prompt={est_prompt_tokens},num_predict={num_predict},window={context_window}"
        super().__init__(LLM_CONTEXT_OVERFLOW, provider=provider, model=model,
                         retryable=False, detail=detail)


class LlmBusyError(LLMProviderError):
    """The single-slot concurrency gate could not be acquired in time.

    Mapped by the API layer to 503 + a friendly retry message; the request is
    never queued indefinitely behind a running inference.
    """

    def __init__(self, waited_s: float, provider: str = "", model: str = ""):
        self.waited_s = waited_s
        super().__init__(LLM_BUSY, provider=provider, model=model,
                         retryable=True, detail=f"waited={waited_s:.1f}s")


class LlmTimeoutError(LLMProviderError):
    """Inference exceeded its wall-clock budget and was force-aborted.

    ``partial_text`` holds whatever was streamed before the circuit-break, so
    callers may surface or discard it; the guard never auto-retries or enlarges
    the budget.
    """

    def __init__(self, timeout_s: float, partial_text: str = "", reason: str = "timeout",
                 provider: str = "", model: str = ""):
        self.timeout_s = timeout_s
        self.partial_text = partial_text
        self.reason = reason
        super().__init__(LLM_PROVIDER_TIMEOUT, provider=provider, model=model,
                         retryable=False, detail=f"{reason}={timeout_s:.1f}s")


class LlmAbortedError(LLMProviderError):
    """Inference was cancelled by an external signal (client disconnect).

    Distinct from a timeout: the request was cut short because the caller went
    away, not because it ran too long. The Ollama stream is closed so the model
    stops generating.
    """

    def __init__(self, partial_text: str = "", reason: str = "client_disconnect",
                 provider: str = "", model: str = ""):
        self.partial_text = partial_text
        self.reason = reason
        super().__init__(LLM_ABORTED, provider=provider, model=model,
                         retryable=False, detail=reason)
