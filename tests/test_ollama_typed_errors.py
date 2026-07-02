"""Ollama typed invalid/empty-output failures (PR27 salvage, PR29-compatible).

Empty/malformed/non-object model output must be a typed failure requiring manual
review — never a false success (main previously returned ``{}`` for garbage).
Through the PR29 gateway this surfaces as provider_ok=false / local_call_failed,
with NO external API and NO mock fallback.
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
from aivan.llm import gateway
from aivan.llm.gateway import llm_complete_json, reset_provider
from aivan.llm.policy import LocalModelUnavailableError
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
    monkeypatch.setenv("AIVAN_LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")
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
    # No prompt / model leak in the message.
    assert "qwen3.5:2b" not in str(err)
    assert "secret user prompt" not in str(err)
    return err


# ── empty / malformed / non-object -> typed error, not {} success ────────────

def test_empty_output_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response(""), LLM_EMPTY_RESPONSE)


def test_whitespace_output_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("  \n\t "), LLM_EMPTY_RESPONSE)


def test_null_output_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("null"), LLM_EMPTY_RESPONSE)


def test_empty_object_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("{}"), LLM_EMPTY_RESPONSE)


def test_malformed_json_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response('{"a": 1'), LLM_INVALID_JSON)


def test_json_array_is_unsupported(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response("[1,2,3]"), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_json_scalar_is_unsupported(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: _content_response('"a string"'), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_timeout_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(httpx.TimeoutException("t")), LLM_PROVIDER_TIMEOUT)


def test_connection_error_raises_typed_error(monkeypatch):
    _expect_error(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")), LLM_PROVIDER_CONNECTION_ERROR)


def test_text_around_json_is_recovered(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _content_response('Sure: {"risk": "low", "ok": true} done'))
    assert OllamaProvider().complete_json("t", "system", "user", {}) == {"risk": "low", "ok": True}


def test_valid_json_still_passes(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _content_response('{"ok": true}'))
    assert OllamaProvider().complete_json("t", "system", "user", {}) == {"ok": True}


def test_empty_output_retries_at_most_once(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_MAX_RETRIES", "3")
    reset_provider()
    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return _content_response("")

    _patch_post(monkeypatch, counting)
    with pytest.raises(LLMProviderError):
        OllamaProvider().complete_json("t", "system", "user", {})
    assert calls["n"] == 2  # original + exactly one retry despite max_retries=3


# ── gateway: PR29-compatible (no mock fallback, no external) ─────────────────

def test_gateway_no_mock_fallback_for_real_provider(monkeypatch):
    """A real provider failure fails closed (LocalModelUnavailableError), never mock."""
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("AIVAN_TEST_MODE", raising=False)
    reset_provider()
    monkeypatch.setattr(
        OllamaProvider, "complete_json",
        lambda *a, **k: (_ for _ in ()).throw(LLMProviderError(LLM_EMPTY_RESPONSE, "ollama")),
    )
    with pytest.raises(LocalModelUnavailableError):
        llm_complete_json("trade_risk", "system", "user")


def test_gateway_no_mock_fallback_even_in_test_mode(monkeypatch):
    """PR29 integrity: even AIVAN_TEST_MODE must not turn a garbage local call
    into a fabricated mock success (that would make the benchmark meaningless).
    Only AIVAN_LLM_PROVIDER=mock uses the mock provider."""
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AIVAN_TEST_MODE", "true")
    reset_provider()
    monkeypatch.setattr(
        OllamaProvider, "complete_json",
        lambda *a, **k: (_ for _ in ()).throw(LLMProviderError(LLM_INVALID_JSON, "ollama")),
    )
    with pytest.raises(LocalModelUnavailableError):
        llm_complete_json("trade_risk", "system", "user")


def test_gateway_telemetry_marks_provider_not_ok_on_typed_error(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    reset_provider()
    monkeypatch.setattr(
        OllamaProvider, "complete_json",
        lambda *a, **k: (_ for _ in ()).throw(LLMProviderError(LLM_INVALID_JSON, "ollama")),
    )
    events = []
    gateway.add_call_observer(events.append)
    try:
        with pytest.raises(LocalModelUnavailableError):
            llm_complete_json("trade_risk", "system", "user")
    finally:
        gateway.remove_call_observer(events.append)
    assert events and events[-1].ok is False
    assert events[-1].external_api_called is False
    assert events[-1].fell_back_to_mock is False


def test_mock_provider_still_works_when_configured(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "mock")
    reset_provider()
    result = llm_complete_json("requirement_structuring", "system", "user")
    assert isinstance(result, dict) and result
