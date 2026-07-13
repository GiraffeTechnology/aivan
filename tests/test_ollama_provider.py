import json

import httpx
import pytest

from aivan.llm import guard as guard_mod
from aivan.llm.gateway import get_provider, reset_provider
from aivan.llm.providers.ollama_provider import OllamaProvider


def _stream_response(content: str, done_reason: str = "stop") -> httpx.Response:
    lines = [
        json.dumps({"message": {"role": "assistant", "content": content}, "done": False}),
        json.dumps({"done": True, "done_reason": done_reason}),
    ]
    return httpx.Response(200, content=("\n".join(lines) + "\n").encode())


@pytest.fixture(autouse=True)
def reset_llm_provider():
    reset_provider()
    guard_mod.reset_gate()
    yield
    guard_mod.set_test_transport(None)
    guard_mod.reset_gate()
    reset_provider()


def test_gateway_selects_ollama_provider(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")

    provider = get_provider()

    assert isinstance(provider, OllamaProvider)


def test_ollama_provider_streams_guarded_chat(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _stream_response('{"ok": true, "provider": "ollama"}')

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    guard_mod.set_test_transport(httpx.MockTransport(handler))

    result = OllamaProvider().complete_json(
        "ollama_smoke",
        "Return valid JSON only.",
        'Return exactly {"ok": true, "provider": "ollama"}',
        {},
        temperature=0,
    )

    assert result == {"ok": True, "provider": "ollama"}
    body = captured["body"]
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert body["model"] == "qwen3.5:2b"
    # Token Guard invariants on the wire body:
    assert body["stream"] is True
    assert body["think"] is False
    assert body["format"] == "json"
    assert "num_predict" in body["options"]
    assert 1 <= body["options"]["num_predict"] <= 2048


def test_ollama_provider_hides_payload_on_failure(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    guard_mod.set_test_transport(httpx.MockTransport(boom))

    with pytest.raises(RuntimeError) as exc:
        OllamaProvider().complete_json("task", "system", "secret user prompt", {})

    assert "qwen3.5:2b" not in str(exc.value)
    assert "secret user prompt" not in str(exc.value)
