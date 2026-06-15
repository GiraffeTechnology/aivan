import os
import httpx
from aivan.llm.base import LLMProvider
from aivan.llm.json_utils import safe_json_loads

class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        self.timeout = int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {
            "model": self.model, "max_tokens": 4096,
            "system": system_prompt + "\n\nAlways respond with valid JSON only.",
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
        }
        response = httpx.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        content = response.json()["content"][0]["text"]
        return safe_json_loads(content, {})
