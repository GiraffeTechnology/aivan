import pytest

from aivan.llm.gateway import get_provider, reset_provider
from aivan.llm.providers.ollama_provider import OllamaProvider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def reset_llm_provider():
    reset_provider()
    yield
    reset_provider()


def test_gateway_selects_ollama_provider(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")

    provider = get_provider()

    assert isinstance(provider, OllamaProvider)


def test_ollama_provider_uses_native_chat_without_qwen_key(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return _Response(
            {
                "message": {
                    "role": "assistant",
                    "content": '{"ok": true, "provider": "ollama"}',
                }
            }
        )

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setattr("aivan.llm.providers.ollama_provider.httpx.post", fake_post)

    result = OllamaProvider().complete_json(
        "ollama_smoke",
        "Return valid JSON only.",
        'Return exactly {"ok": true, "provider": "ollama"}',
        {},
        temperature=0,
    )

    assert result == {"ok": True, "provider": "ollama"}
    assert len(calls) == 1
    assert calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert calls[0]["json"]["model"] == "qwen3.5:2b"
    assert calls[0]["json"]["stream"] is False
    assert calls[0]["json"]["think"] is False
    assert calls[0]["json"]["format"] == "json"


def test_ollama_provider_retries_and_hides_payload(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")
    monkeypatch.setenv("AIVAN_LLM_MAX_RETRIES", "0")
    monkeypatch.setattr(
        "aivan.llm.providers.ollama_provider.httpx.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")),
    )

    with pytest.raises(RuntimeError) as exc:
        OllamaProvider().complete_json("task", "system", "user", {})

    assert "qwen3.5:2b" not in str(exc.value)
    assert "user" not in str(exc.value)
