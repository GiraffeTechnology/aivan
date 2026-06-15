import os
import httpx
from aivan.llm.base import LLMProvider
from aivan.llm.json_utils import safe_json_loads

class GoogleProvider(LLMProvider):
    provider_name = "google"

    def __init__(self):
        self.api_key = os.environ.get("GOOGLE_API_KEY", "")
        self.model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        self.timeout = int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY not set")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"{system_prompt}\n\n{user_prompt}\n\nRespond with valid JSON only."}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
        }
        response = httpx.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return safe_json_loads(content, {})
