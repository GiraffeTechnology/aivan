"""Ollama typed invalid/empty-output failures (PR27 salvage, PR29-compatible).

Empty/malformed/non-object model output must be a typed failure requiring manual
review — never a false success (main previously returned ``{}`` for garbage).
Through the PR29 gateway this surfaces as provider_ok=false / local_call_failed,
with NO external API and NO mock fallback.

All local inference now goes through the Token Guard, which streams the call, so
these tests drive the guard's injected mock transport (streamed Ollama JSONL)
rather than patching a one-shot ``httpx.post``.
"""
import json

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
from aivan.llm import guard as guard_mod
from aivan.llm.gateway import llm_complete_json, reset_provider
from aivan.llm.policy import LocalModelUnavailableError
from aivan.llm.providers.ollama_provider import OllamaProvider


def _stream_response(content: str, done_reason: str = "stop") -> httpx.Response:
    """A completed Ollama /api/chat stream carrying ``content`` in one chunk."""
    lines = [
        json.dumps({"message": {"role": "assistant", "content": content}, "done": False}),
        json.dumps({"done": True, "done_reason": done_reason}),
    ]
    return httpx.Response(200, content=("\n".join(lines) + "\n").encode())


def _transport_returning(content: str, done_reason: str = "stop") -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: _stream_response(content, done_reason))


def _transport_raising(exc: Exception) -> httpx.MockTransport:
    def handler(req):
        raise exc
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:2b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    reset_provider()
    guard_mod.reset_gate()
    yield
    guard_mod.set_test_transport(None)
    guard_mod.reset_gate()
    reset_provider()


def _expect_error(transport, code):
    guard_mod.set_test_transport(transport)
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

def test_empty_output_raises_typed_error():
    _expect_error(_transport_returning(""), LLM_EMPTY_RESPONSE)


def test_whitespace_output_raises_typed_error():
    _expect_error(_transport_returning("  \n\t "), LLM_EMPTY_RESPONSE)


def test_null_output_raises_typed_error():
    _expect_error(_transport_returning("null"), LLM_EMPTY_RESPONSE)


def test_empty_object_raises_typed_error():
    _expect_error(_transport_returning("{}"), LLM_EMPTY_RESPONSE)


def test_malformed_json_raises_typed_error():
    _expect_error(_transport_returning('{"a": 1'), LLM_INVALID_JSON)


def test_json_array_is_unsupported():
    _expect_error(_transport_returning("[1,2,3]"), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_json_scalar_is_unsupported():
    _expect_error(_transport_returning('"a string"'), LLM_PROVIDER_UNSUPPORTED_RESPONSE)


def test_truncated_length_is_invalid_and_not_retried():
    # done_reason=length -> partial JSON -> INVALID (manual review), never retried.
    _expect_error(_transport_returning('{"a":', done_reason="length"), LLM_INVALID_JSON)


def test_timeout_raises_typed_error():
    _expect_error(_transport_raising(httpx.ReadTimeout("t")), LLM_PROVIDER_TIMEOUT)


def test_connection_error_raises_typed_error():
    _expect_error(_transport_raising(httpx.ConnectError("refused")), LLM_PROVIDER_CONNECTION_ERROR)


def test_text_around_json_is_recovered():
    guard_mod.set_test_transport(_transport_returning('Sure: {"risk": "low", "ok": true} done'))
    assert OllamaProvider().complete_json("t", "system", "user", {}) == {"risk": "low", "ok": True}


def test_valid_json_still_passes():
    guard_mod.set_test_transport(_transport_returning('{"ok": true}'))
    assert OllamaProvider().complete_json("t", "system", "user", {}) == {"ok": True}


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
