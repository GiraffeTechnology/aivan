import os
import httpx
from aiven.llm.base import LLMProvider
from aiven.llm.json_utils import safe_json_loads

class DeepSeekProvider(LLMProvider):
    provider_name = "deepseek"

    def __init__(self):
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.timeout = int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt + "\n\nRespond with valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        response = httpx.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return safe_json_loads(content, {})
