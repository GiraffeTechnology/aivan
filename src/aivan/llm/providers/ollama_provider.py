import os

import httpx

from aivan.llm.base import LLMProvider
from aivan.llm.json_utils import safe_json_loads


class OllamaProvider(LLMProvider):
    """Local LLM via Ollama's OpenAI-compatible /v1/chat/completions endpoint.

    Primary (local-first) extractor for the supplier-signal layer; fails fast so
    callers can fall back to a hosted provider (DashScope Qwen) on error/timeout.
    """

    provider_name = "ollama"

    def __init__(self) -> None:
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
        self.model = os.environ.get("OLLAMA_MODEL", "qwen2.5")
        # Local-first: short timeout so a stalled local server falls back quickly.
        self.timeout = float(os.environ.get("AIVAN_OLLAMA_TIMEOUT_SECONDS", "10"))

    def complete_json(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict,
        temperature: float = 0.0,
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        response = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return safe_json_loads(content, {})
