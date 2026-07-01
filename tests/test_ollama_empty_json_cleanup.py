"""PR19 cleanup regression tests: Ollama empty / invalid JSON handling.

Invalid or empty model output must be a controlled, typed failure that requires
manual review — never a false success, and never a fabricated assessment. See
CLAUDE task Part A (§5).
"""
import httpx
import pytest

from aivan.llm.errors import (
    LLM_EMPTY_RESPONSE,
    LLM_INVALID_JSON,
    LLM_PROVIDER_CONNECTION_ERROR,
    LLM_PROVIDER_TIMEOUT,
    LLM_PROVIDER_UNSUPPORTED_RESPONSE,
    LLMProviderError,
)
from aivan.llm.gateway import llm_complete_json, reset_provider
from aivan.llm.providers.ollama_provider import OllamaProvider


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _content_response(content):
    return _Response({"message": {"role": "assistant", "content": content}})


@pytest.fixture(autouse=True)
def _no_retries_and_reset(monkeypatch):
    # Deterministic single-attempt behavior for classification assertions.
    monkeypatch.setenv("AIVAN_LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:0.8b")
    reset_provider()
    yield
    reset_provider()


def _patch_post(monkeypatch, fn):
    monkeypatch.setattr("aivan.llm.providers.ollama_provider.httpx.post", fn)


def _expect_error(monkeypatch, post_fn, code):
    _patch_post(monkeypatch, post_fn)
    with pytest.raises(LLMProviderError) as exc:
        OllamaProvider().complete_json("trade_risk", "system", "secret user prompt", {})
    err = exc.value
    assert err.error_code == code
    assert err.manual_review_required is True
    # Secrets: neither the model name nor the prompt may leak into the message.
    assert "qwen3.5:0.8b" not in str(err)
    assert "secret user prompt" not in str(err)
    return err


def test_empty_body(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response(""), LLM_EMPTY_RESPONSE)


def test_whitespace_body(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("   \n\t "), LLM_EMPTY_RESPONSE)


def test_null_body(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("null"), LLM_EMPTY_RESPONSE)


def test_empty_object(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("{}"), LLM_EMPTY_RESPONSE)


def test_malformed_json(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response('{"a": 1'), LLM_INVALID_JSON)


def test_json_array(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("[1, 2, 3]"), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_json_string_scalar(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response('"just a string"'), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_timeout(monkeypatch):
    def boom(*a, **k):
        raise httpx.TimeoutException("timed out")

    _expect_error(monkeypatch, boom, LLM_PROVIDER_TIMEOUT)


def test_connection_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("connection refused")

    _expect_error(monkeypatch, boom, LLM_PROVIDER_CONNECTION_ERROR)


def test_text_around_json_is_recovered(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _content_response('Sure, here: {"risk": "low", "ok": true} done'))
    result = OllamaProvider().complete_json("trade_risk", "system", "user", {})
    assert result == {"risk": "low", "ok": True}


def test_valid_json_still_passes(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _content_response('{"ok": true, "provider": "ollama"}'))
    result = OllamaProvider().complete_json("trade_risk", "system", "user", {})
    assert result == {"ok": True, "provider": "ollama"}


def test_empty_response_retries_at_most_once(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_MAX_RETRIES", "3")
    reset_provider()
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return _content_response("")

    _patch_post(monkeypatch, counting)
    with pytest.raises(LLMProviderError) as exc:
        OllamaProvider().complete_json("trade_risk", "system", "user", {})
    assert exc.value.error_code == LLM_EMPTY_RESPONSE
    # Original attempt + exactly one retry, despite max_retries=3.
    assert calls["n"] == 2


def test_gateway_fails_closed_for_real_provider(monkeypatch):
    """A real provider failure must NOT be silently replaced by a mock result."""
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)
    reset_provider()
    monkeypatch.setattr(
        OllamaProvider,
        "complete_json",
        lambda *a, **k: (_ for _ in ()).throw(LLMProviderError(LLM_EMPTY_RESPONSE, "ollama")),
    )
    with pytest.raises(LLMProviderError):
        llm_complete_json("trade_risk", "system", "user")


def test_gateway_mock_fallback_only_in_test_mode(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AIVAN_TEST_MODE", "true")
    reset_provider()
    monkeypatch.setattr(
        OllamaProvider,
        "complete_json",
        lambda *a, **k: (_ for _ in ()).throw(LLMProviderError(LLM_EMPTY_RESPONSE, "ollama")),
    )
    result = llm_complete_json("trade_risk", "system", "user")
    assert isinstance(result, dict)
