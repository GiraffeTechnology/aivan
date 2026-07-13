import json
import os

from aivan.llm.base import LLMProvider
from aivan.llm.errors import (
    LLM_EMPTY_RESPONSE,
    LLM_INVALID_JSON,
    LLM_PROVIDER_UNSUPPORTED_RESPONSE,
    LLMProviderError,
)
from aivan.llm.guard import LlmTokenGuard
from aivan.llm.guard_config import resolve_profile
from aivan.llm.json_utils import extract_json


class OllamaProvider(LLMProvider):
    """Local Ollama provider. All inference is routed through the Token Guard.

    The provider never talks to the socket directly: it builds the chat messages
    and hands them to :class:`LlmTokenGuard`, which forces a bounded
    ``num_predict``, a streamed call, a wall-clock circuit-break, real
    cancellation, and the single-slot concurrency gate. The provider's own job is
    only to select a profile from the task and to classify the returned text into
    a JSON object (or a typed failure requiring manual review).
    """

    provider_name = "ollama"

    def __init__(self):
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "qwen3.5:2b")
        self._guard = LlmTokenGuard(provider_name=self.provider_name)

    def _error(self, code: str, detail: str = "") -> LLMProviderError:
        # Never pass prompts, messages, or provider bodies into ``detail``.
        return LLMProviderError(code, provider=self.provider_name, model=self.model, detail=detail)

    def complete_json(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict,
        temperature: float = 0.0,
    ) -> dict:
        profile = resolve_profile(None, task)
        messages = [
            {"role": "system", "content": system_prompt + "\n\nReturn valid JSON only."},
            {"role": "user", "content": user_prompt},
        ]

        # The guard raises its own typed control-flow errors (busy / timeout /
        # aborted / context overflow) which propagate unchanged for the caller
        # to handle. Everything below only deals with a *completed* stream.
        result = self._guard.stream_chat(
            base_url=self.base_url,
            model=self.model,
            messages=messages,
            profile=profile,
            response_format="json",
            temperature=temperature,
        )

        # A truncated JSON answer is unusable and must never be auto-retried or
        # auto-enlarged — surface it as invalid for manual review.
        if result.truncated:
            raise self._error(LLM_INVALID_JSON, "truncated")

        content = result.text.strip() if isinstance(result.text, str) else ""
        if not content or content.lower() == "null":
            raise self._error(LLM_EMPTY_RESPONSE, "empty_content")

        status, value = _classify_content(content)
        if status == "ok":
            return value
        if status == "empty":
            raise self._error(LLM_EMPTY_RESPONSE, "empty_object")
        if status == "unsupported":
            raise self._error(LLM_PROVIDER_UNSUPPORTED_RESPONSE, "non_object_json")
        raise self._error(LLM_INVALID_JSON, "unparseable")


def _classify_content(content: str) -> tuple[str, dict]:
    """Classify raw model content into (status, value).

    status is one of: ok | empty | unsupported | invalid.
    """
    try:
        parsed = json.loads(content)
    except Exception:
        recovered = extract_json(content)  # handles text-around-JSON / code fences
        if isinstance(recovered, dict) and recovered:
            return "ok", recovered
        return "invalid", {}
    if isinstance(parsed, dict):
        return ("ok", parsed) if parsed else ("empty", {})
    # Valid JSON but not an object: array, string, number, bool, or null.
    return "unsupported", {}
