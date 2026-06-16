import base64
import os
import time
from pathlib import Path

import httpx
from aivan.llm.base import LLMProvider
from aivan.llm.config import get_llm_max_retries
from aivan.llm.json_utils import safe_json_loads


def _encode_image_content(path_or_url: str) -> dict:
    """Return an OpenAI-compatible image content block for DashScope's compatible-mode API."""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        url = path_or_url
    else:
        p = Path(path_or_url)
        data = base64.b64encode(p.read_bytes()).decode()
        suffix = p.suffix.lstrip(".").lower() or "jpeg"
        url = f"data:image/{suffix};base64,{data}"
    return {"type": "image_url", "image_url": {"url": url}}


class QwenProvider(LLMProvider):
    provider_name = "qwen"

    def __init__(self):
        self.api_key = os.environ.get("QWEN_API_KEY", "")
        self.base_url = os.environ.get("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = os.environ.get("QWEN_MODEL", "qwen-turbo")
        self.vision_model = os.environ.get("QWEN_VISION_MODEL", "qwen-vl-plus")
        self.timeout = int(os.environ.get("AIVAN_LLM_TIMEOUT_SECONDS", "30"))
        self.max_retries = get_llm_max_retries()

    def _post_with_retries(self, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError("QWEN_API_KEY not set")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                # 4xx errors (bad request, invalid image size, auth, etc.) are not transient — retrying wastes quota.
                if 400 <= exc.response.status_code < 500:
                    raise RuntimeError(f"Qwen API rejected the request: {exc.response.text}") from exc
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Qwen API call failed after {self.max_retries + 1} attempts: {last_exc}") from last_exc

    def complete_json(self, task: str, system_prompt: str, user_prompt: str, schema_hint: dict, temperature: float = 0.0) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt + "\n\nRespond with valid JSON only."},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        raw = self._post_with_retries(payload)
        content = raw["choices"][0]["message"]["content"]
        return safe_json_loads(content, {})

    def compare_images(self, images: list[str], question: str, system_prompt: str = None, temperature: float = 0.0) -> dict:
        """Ask the Qwen vision model to compare/inspect one or more images and return parsed JSON."""
        content = [_encode_image_content(img) for img in images]
        content.append({"type": "text", "text": question})

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt + "\n\nRespond with valid JSON only."})
        messages.append({"role": "user", "content": content})

        payload = {
            "model": self.vision_model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        raw = self._post_with_retries(payload)
        text = raw["choices"][0]["message"]["content"]
        return safe_json_loads(text, {})

    def compare_video_frames(self, frames: list[str], question: str, system_prompt: str = None, temperature: float = 0.0) -> dict:
        """Compare a sequence of video frames; thin wrapper over compare_images."""
        return self.compare_images(frames, question, system_prompt=system_prompt, temperature=temperature)
