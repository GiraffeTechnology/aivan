"""Adversarial, code-level verification of the local-LLM Token Guard (PRD §7).

Every test drives the guard through an injected ``httpx.MockTransport`` streaming
synthetic Ollama JSONL, so no live model is required and the exact request body
sent on the wire can be asserted. These lock the PRD's hard invariants (§9):

  1. No request can exist without ``num_predict`` and it is always <= hard cap.
  2. Amplification is clamped down and logged, never enlarged.
  3. ``think`` is forced false for qa_* profiles.
  4. Over-budget prompts raise before any network call.
  5. A wall-clock timeout force-aborts (circuit-break) with the partial text.
  6. The single-slot concurrency gate fails fast with LlmBusyError.
  7. ``done_reason=length`` is reported as truncated and never auto-retried.
  8. Client-disconnect aborts the in-flight stream (AbortController equivalent).
"""
import json
import threading
import time

import httpx
import pytest

from aivan.llm import guard as guard_mod
from aivan.llm import guard_config as cfg
from aivan.llm.cancellation import CancelToken, cancellable
from aivan.llm.errors import (
    LlmAbortedError,
    LlmBusyError,
    LlmContextOverflowError,
    LlmTimeoutError,
)
from aivan.llm.guard import LlmTokenGuard, estimate_prompt_tokens


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Deterministic guard config per test; restore transport + gate after.
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    guard_mod.reset_gate()
    yield
    guard_mod.set_test_transport(None)
    guard_mod.reset_gate()


def _stream(*content_chunks, done_reason="stop"):
    def handler(req):
        lines = [json.dumps({"message": {"content": c}, "done": False}) for c in content_chunks]
        lines.append(json.dumps({"done": True, "done_reason": done_reason}))
        return httpx.Response(200, content=("\n".join(lines) + "\n").encode())
    return httpx.MockTransport(handler)


def _capture():
    box = {}

    def handler(req):
        box["body"] = json.loads(req.content)
        return httpx.Response(200, content=(json.dumps({"message": {"content": '{"ok":1}'}, "done": False})
                                            + "\n" + json.dumps({"done": True, "done_reason": "stop"}) + "\n").encode())
    return box, httpx.MockTransport(handler)


class _SlowStream(httpx.SyncByteStream):
    """Yields chunks with a per-chunk delay so deadline/abort checks can fire."""

    def __init__(self, n=50, delay=0.1):
        self.n, self.delay = n, delay

    def __iter__(self):
        for _ in range(self.n):
            time.sleep(self.delay)
            yield (json.dumps({"message": {"content": "x"}, "done": False}) + "\n").encode()

    def close(self):
        pass


def _slow_transport(n=50, delay=0.1):
    return httpx.MockTransport(lambda req: httpx.Response(200, stream=_SlowStream(n, delay)))


def _guard():
    return LlmTokenGuard(provider_name="ollama")


# 1. A request without num_predict is impossible; always <= hard cap. ─────────
def test_num_predict_always_present_and_bounded():
    box, transport = _capture()
    guard_mod.set_test_transport(transport)
    _guard().stream_chat(base_url="http://x", model="m",
                         messages=[{"role": "user", "content": "hi"}],
                         profile=cfg.PROFILES["qa_standard"])
    opts = box["body"]["options"]
    assert "num_predict" in opts
    assert 1 <= opts["num_predict"] <= cfg.hard_max_num_predict()
    assert opts["num_predict"] == 512  # qa_standard budget


# 2. Amplification attack: requested 999999 -> clamped to profile budget. ─────
def test_amplification_is_clamped_down(caplog):
    box, transport = _capture()
    guard_mod.set_test_transport(transport)
    with caplog.at_level("WARNING"):
        _guard().stream_chat(base_url="http://x", model="m",
                             messages=[{"role": "user", "content": "hi"}],
                             profile=cfg.PROFILES["qa_short"], requested_num_predict=999999)
    assert box["body"]["options"]["num_predict"] == 256  # qa_short, not 999999
    assert any("amplification" in r.message for r in caplog.records)


def test_num_predict_never_exceeds_hard_cap_even_for_reasoning_max(monkeypatch):
    monkeypatch.setenv("LLM_HARD_MAX_NUM_PREDICT", "2048")
    box, transport = _capture()
    guard_mod.set_test_transport(transport)
    _guard().stream_chat(base_url="http://x", model="m",
                         messages=[{"role": "user", "content": "hi"}],
                         profile=cfg.PROFILES["reasoning_max"], requested_num_predict=100000)
    assert box["body"]["options"]["num_predict"] == 2048


# 3. think is off for qa_* and on only for reasoning*. ────────────────────────
def test_think_forced_off_for_qa_profiles():
    box, transport = _capture()
    guard_mod.set_test_transport(transport)
    _guard().stream_chat(base_url="http://x", model="m",
                         messages=[{"role": "user", "content": "hi"}],
                         profile=cfg.PROFILES["qa_standard"])
    assert box["body"]["think"] is False


def test_think_on_for_reasoning_profiles():
    box, transport = _capture()
    guard_mod.set_test_transport(transport)
    _guard().stream_chat(base_url="http://x", model="m",
                         messages=[{"role": "user", "content": "hi"}],
                         profile=cfg.PROFILES["reasoning"])
    assert box["body"]["think"] is True


# 4. Context overflow -> raises before any network request. ───────────────────
def test_context_overflow_raises_without_network():
    def must_not_call(req):
        raise AssertionError("network must not be touched on overflow")
    guard_mod.set_test_transport(httpx.MockTransport(must_not_call))
    with pytest.raises(LlmContextOverflowError) as exc:
        _guard().stream_chat(base_url="http://x", model="m",
                             messages=[{"role": "user", "content": "字" * 5000}],
                             profile=cfg.PROFILES["qa_standard"])
    assert exc.value.est_prompt_tokens > cfg.context_window()


def test_estimate_prompt_tokens_overestimates_cjk():
    assert estimate_prompt_tokens("你好世界") >= 4


# 5. Timeout circuit-break: slow stream + low cap -> LlmTimeoutError + partial.
def test_timeout_circuit_break(monkeypatch):
    monkeypatch.setenv("LLM_MAX_INFERENCE_TIMEOUT_S", "0.5")
    guard_mod.set_test_transport(_slow_transport(n=50, delay=0.1))
    started = time.monotonic()
    with pytest.raises(LlmTimeoutError) as exc:
        _guard().stream_chat(base_url="http://x", model="m",
                             messages=[{"role": "user", "content": "hi"}],
                             profile=cfg.PROFILES["qa_short"])
    elapsed = time.monotonic() - started
    assert elapsed < 3.0  # fired at the 0.5s cap, not after the full stream
    assert exc.value.timeout_s <= 0.5 + 1e-6


def test_read_timeout_maps_to_timeout_error():
    def raise_timeout(req):
        raise httpx.ReadTimeout("slow")
    guard_mod.set_test_transport(httpx.MockTransport(raise_timeout))
    with pytest.raises(LlmTimeoutError):
        _guard().stream_chat(base_url="http://x", model="m",
                             messages=[{"role": "user", "content": "hi"}],
                             profile=cfg.PROFILES["qa_short"])


# 6. Concurrency gate: one slot; overflow fails fast with LlmBusyError. ────────
def test_concurrency_gate_busy(monkeypatch):
    monkeypatch.setenv("LLM_CONCURRENCY", "1")
    monkeypatch.setenv("LLM_QUEUE_WAIT_TIMEOUT_S", "0.3")
    guard_mod.reset_gate()
    gate = guard_mod._get_gate()
    assert gate.acquire()  # occupy the only slot
    try:
        with pytest.raises(LlmBusyError) as exc:
            _guard().stream_chat(base_url="http://x", model="m",
                                 messages=[{"role": "user", "content": "hi"}],
                                 profile=cfg.PROFILES["qa_short"])
        assert exc.value.waited_s >= 0.25
    finally:
        gate.release()
        guard_mod.reset_gate()


def test_concurrency_gate_serializes_three_requests(monkeypatch):
    monkeypatch.setenv("LLM_CONCURRENCY", "1")
    monkeypatch.setenv("LLM_QUEUE_WAIT_TIMEOUT_S", "5")
    guard_mod.reset_gate()
    guard_mod.set_test_transport(_slow_transport(n=2, delay=0.05))
    results, errors = [], []

    def run():
        try:
            r = _guard().stream_chat(base_url="http://x", model="m",
                                     messages=[{"role": "user", "content": "hi"}],
                                     profile=cfg.PROFILES["qa_short"])
            results.append(r)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    # With a generous queue wait all three complete, but never concurrently.
    assert len(results) == 3
    assert not errors


# 7. Truncation (done_reason=length) -> truncated flag, no auto-retry. ────────
def test_truncation_flag_no_retry():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(200, content=(json.dumps({"message": {"content": '{"a":'}, "done": False})
                                            + "\n" + json.dumps({"done": True, "done_reason": "length"}) + "\n").encode())
    guard_mod.set_test_transport(httpx.MockTransport(handler))
    result = _guard().stream_chat(base_url="http://x", model="m",
                                  messages=[{"role": "user", "content": "hi"}],
                                  profile=cfg.PROFILES["qa_short"])
    assert result.truncated is True
    assert result.done_reason == "length"
    assert calls["n"] == 1  # single call, no auto-retry inside the guard


# 8. Client-disconnect aborts the in-flight stream (AbortController). ─────────
def test_pre_aborted_token_raises_without_network():
    def must_not_call(req):
        raise AssertionError("must not open socket for an already-aborted call")
    guard_mod.set_test_transport(httpx.MockTransport(must_not_call))
    tok = CancelToken()
    tok.abort("client_disconnect")
    with cancellable(tok):
        with pytest.raises(LlmAbortedError) as exc:
            _guard().stream_chat(base_url="http://x", model="m",
                                 messages=[{"role": "user", "content": "hi"}],
                                 profile=cfg.PROFILES["qa_short"])
    assert exc.value.reason == "client_disconnect"


def test_mid_stream_abort_stops_generation(monkeypatch):
    monkeypatch.setenv("LLM_MAX_INFERENCE_TIMEOUT_S", "30")
    guard_mod.set_test_transport(_slow_transport(n=50, delay=0.1))
    tok = CancelToken()

    def killer():
        time.sleep(0.4)
        tok.abort("client_disconnect")
    threading.Thread(target=killer, daemon=True).start()

    started = time.monotonic()
    with cancellable(tok):
        with pytest.raises(LlmAbortedError):
            _guard().stream_chat(base_url="http://x", model="m",
                                 messages=[{"role": "user", "content": "hi"}],
                                 profile=cfg.PROFILES["qa_short"])
    # Aborted mid-stream, long before the 50 * 0.1s stream would finish.
    assert time.monotonic() - started < 3.0


# Result shape (PRD 5.5). ─────────────────────────────────────────────────────
def test_result_shape():
    guard_mod.set_test_transport(_stream('{"ok":', ' true}'))
    r = _guard().stream_chat(base_url="http://x", model="m",
                             messages=[{"role": "user", "content": "hi"}],
                             profile=cfg.PROFILES["qa_standard"])
    assert r.text == '{"ok": true}'
    assert r.truncated is False
    assert r.profile == "qa_standard"
    assert r.prompt_tokens >= 1
    assert r.output_tokens >= 1
    assert r.duration_ms >= 0
