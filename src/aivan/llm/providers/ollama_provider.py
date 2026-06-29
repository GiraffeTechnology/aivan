import os
from urllib.parse import urljoin

import httpx

from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_max_retries, get_llm_timeout
from aivan.llm.json_utils import safe_json_loads


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    def __init__(self):
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "qwen3.5:0.8b")
        self.timeout = get_llm_timeout()
        self.max_retries = get_llm_max_retries()

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
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    urljoin(self.base_url.rstrip("/") + "/", "api/chat"),
                    json=request_body,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                return safe_json_loads(content, {})
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Ollama request failed after retries: {last_error}")
