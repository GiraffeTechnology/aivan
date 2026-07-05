"""Shared base for OpenAI-compatible chat-completions providers.

OpenAI, DeepSeek, and Qwen (DashScope compatible mode) all speak the same
``POST {base_url}/chat/completions`` protocol; only the env-var prefix,
defaults, JSON-mode prompt suffix, and retry policy differ per provider.
"""

from __future__ import annotations

import os

import httpx

from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_timeout
from aivan.llm.json_utils import safe_json_loads


class OpenAICompatProvider(LLMProvider):
    """Base class; subclasses set the env prefix, defaults, and retry policy."""

    env_prefix: str = ""
    default_base_url: str = ""
    default_model: str = ""
    # Appended to the system prompt for backends without reliable JSON mode.
    json_prompt_suffix: str = ""
    # Number of retries after the first attempt (0 = single attempt).
    max_retries: int = 0

    def __init__(self):
        self.api_key = os.environ.get(f"{self.env_prefix}_API_KEY", "")
        self.base_url = os.environ.get(f"{self.env_prefix}_BASE_URL", self.default_base_url)
        self.model = os.environ.get(f"{self.env_prefix}_MODEL", self.default_model)
        self.timeout = get_llm_timeout()

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        if not self.api_key:
            raise RuntimeError(f"{self.env_prefix}_API_KEY not set")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt + self.json_prompt_suffix},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                response = httpx.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return safe_json_loads(content, {})
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"{self.provider_name} request failed after retries: {last_error}")
