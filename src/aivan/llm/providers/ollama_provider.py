import json
import os
from urllib.parse import urljoin

import httpx

from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_max_retries, get_llm_timeout
from aivan.llm.errors import (
    LLM_EMPTY_RESPONSE,
    LLM_INVALID_JSON,
    LLM_PROVIDER_CONNECTION_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_PROVIDER_UNSUPPORTED_RESPONSE,
    LLMProviderError,
)
from aivan.llm.json_utils import extract_json


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self):
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "qwen3.5:0.8b")
        self.timeout = get_llm_timeout()
        self.max_retries = get_llm_max_retries()

    def _error(self, code: str, detail: str = "") -> LLMProviderError:
        # Never pass prompts, messages, or provider bodies into ``detail``.
        return LLMProviderError(code, provider=self.provider_name, model=self.model, detail=detail)

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        request_body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt + "\n\nReturn valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        url = urljoin(self.base_url.rstrip("/") + "/", "api/chat")

        attempts = self.max_retries + 1
        empty_retry_used = False
        last_error: LLMProviderError | None = None

        for attempt in range(attempts):
            # ── Transport ──────────────────────────────────────────────────
            try:
                response = httpx.post(url, json=request_body, timeout=self.timeout)
                response.raise_for_status()
            except httpx.TimeoutException as exc:
                last_error = self._error(LLM_PROVIDER_TIMEOUT, type(exc).__name__)
                continue
            except httpx.HTTPStatusError as exc:
                last_error = self._error(LLM_PROVIDER_CONNECTION_ERROR, f"http_{exc.response.status_code}")
                continue
            except Exception as exc:  # connection reset, DNS, transport, etc.
                last_error = self._error(LLM_PROVIDER_CONNECTION_ERROR, type(exc).__name__)
                continue

            # ── Body extraction ────────────────────────────────────────────
            try:
                body = response.json()
            except Exception:
                body = None
            content = ""
            if isinstance(body, dict):
                message = body.get("message") or {}
                if isinstance(message, dict):
                    content = message.get("content", "") or ""
            content = content.strip() if isinstance(content, str) else ""

            # ── Empty body / whitespace / literal null → retry at most once ─
            if not content or content.lower() == "null":
                last_error = self._error(LLM_EMPTY_RESPONSE, "empty_content")
                if not empty_retry_used and attempt < attempts - 1:
                    empty_retry_used = True
                    continue
                raise last_error

            # ── Parse + classify ───────────────────────────────────────────
            status, value = _classify_content(content)
            if status == "ok":
                return value
            if status == "empty":
                # Model returned a valid but empty object ({}) — no assessment.
                raise self._error(LLM_EMPTY_RESPONSE, "empty_object")
            if status == "unsupported":
                # Valid JSON that is not an object (array/string/number/bool).
                raise self._error(LLM_PROVIDER_UNSUPPORTED_RESPONSE, "non_object_json")
            # Malformed / truncated JSON — do not auto-fill; manual review.
            raise self._error(LLM_INVALID_JSON, "unparseable")

        # Exhausted retries on a transient transport/empty condition.
        raise last_error or self._error(LLM_PROVIDER_CONNECTION_ERROR, "no_response")


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
