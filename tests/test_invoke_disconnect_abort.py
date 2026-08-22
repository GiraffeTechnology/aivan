"""Backend AbortController: client disconnect aborts the in-flight pipeline.

Verifies that the ``/invoke`` wiring (1) propagates a cancel token into the
worker thread that runs the synchronous RFQ pipeline, and (2) aborts that token
when ``request.is_disconnected()`` becomes true — so the Token Guard can stop
Ollama generation instead of finishing work nobody is waiting for.
"""
import asyncio

from aivan.api import main
from aivan.llm.cancellation import get_cancel_token


class _FakeRequest:
    """Reports connected for the first ``disconnect_after`` polls, then dropped."""

    def __init__(self, disconnect_after: int):
        self.polls = 0
        self._threshold = disconnect_after

    async def is_disconnected(self) -> bool:
        self.polls += 1
        return self.polls > self._threshold


def test_disconnect_aborts_worker_thread(monkeypatch):
    observed = {}

    def fake_run(event_data, db):
        token = get_cancel_token()
        observed["token_present"] = token is not None
        # Simulate a long inference that cooperatively waits on the token.
        observed["aborted"] = bool(token and token.wait(timeout=5))
        return {"status": "ok", "reply_text": "done"}

    monkeypatch.setattr(main, "_run_skill_event", fake_run)
    req = _FakeRequest(disconnect_after=1)

    result = asyncio.run(main._run_skill_event_with_abort({"x": 1}, None, req))

    assert observed["token_present"] is True   # contextvar propagated into thread
    assert observed["aborted"] is True         # disconnect aborted the token
    assert result["status"] == "ok"


def test_no_disconnect_completes_normally(monkeypatch):
    def fake_run(event_data, db):
        token = get_cancel_token()
        # Not aborted while the client stays connected.
        return {"status": "ok", "reply_text": "ok", "aborted": bool(token and token.is_aborted())}

    monkeypatch.setattr(main, "_run_skill_event", fake_run)
    req = _FakeRequest(disconnect_after=10_000)

    result = asyncio.run(main._run_skill_event_with_abort({"x": 1}, None, req))

    assert result["status"] == "ok"
    assert result["aborted"] is False
