"""Cooperative cancellation for in-flight local-LLM inference.

This is the backend's ``AbortController`` equivalent. When the frontend user
interrupts the conversation or closes the page, the request handler aborts the
token; the Token Guard checks the token between streamed chunks (and before it
starts) and, on abort, closes the Ollama stream so the model **stops
generating** instead of running to completion on the shared CPU.

The token is carried through the synchronous execution pipeline via a
``ContextVar`` so no business function signature has to change. ``ContextVar``
values propagate into worker threads started with ``asyncio.to_thread`` /
``run_in_threadpool`` (the context is copied at submit time), which is exactly
how the async API routes hand work to the sync pipeline.
"""
from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Optional


class CancelToken:
    """A one-shot, thread-safe cancellation flag with an optional reason."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str = ""
        self._lock = threading.Lock()

    def abort(self, reason: str = "client_disconnect") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = reason
                self._event.set()

    def is_aborted(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._event.wait(timeout)


_current_token: ContextVar[Optional[CancelToken]] = ContextVar("aivan_llm_cancel_token", default=None)


def set_cancel_token(token: Optional[CancelToken]):
    """Bind a cancel token to the current context. Returns the ContextVar token.

    Pass the returned value to :func:`reset_cancel_token` to restore the prior
    binding (use try/finally around the work you want cancellable).
    """
    return _current_token.set(token)


def reset_cancel_token(reset_token) -> None:
    try:
        _current_token.reset(reset_token)
    except (ValueError, LookupError):
        pass


def get_cancel_token() -> Optional[CancelToken]:
    return _current_token.get()


def current_is_aborted() -> bool:
    token = _current_token.get()
    return bool(token and token.is_aborted())


class _CancelScope:
    def __init__(self, token: CancelToken) -> None:
        self.token = token
        self._reset = None

    def __enter__(self) -> CancelToken:
        self._reset = set_cancel_token(self.token)
        return self.token

    def __exit__(self, *exc) -> None:
        if self._reset is not None:
            reset_cancel_token(self._reset)


def cancellable(token: Optional[CancelToken] = None) -> _CancelScope:
    """Context manager that binds ``token`` (or a fresh one) for its body."""
    return _CancelScope(token or CancelToken())


def sleep_until_aborted(token: CancelToken, deadline: float, poll_s: float = 0.2) -> bool:
    """Block until ``token`` is aborted or ``deadline`` (monotonic) passes.

    Returns True if aborted, False if the deadline was reached first.
    """
    while True:
        if token.is_aborted():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if token.wait(min(poll_s, remaining)):
            return True
