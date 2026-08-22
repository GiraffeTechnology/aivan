"""LlmTokenGuard — code-level enforcement for local Ollama inference.

Every local-model request goes through :meth:`LlmTokenGuard.stream_chat`. The
guard makes the PRD's hard invariants structurally true rather than a matter of
caller discipline:

  1. The request body *always* carries ``options.num_predict`` and it is never
     larger than the profile budget or the hard cap. A caller cannot construct a
     request without a bound.
  2. The call is always streamed, with a wall-clock ceiling and *real*
     cancellation — on timeout or client disconnect the stream is closed so
     Ollama stops generating (not just the client giving up).
  3. A single-slot concurrency gate mirrors ``OLLAMA_NUM_PARALLEL=1``; queue
     overflow fails fast with :class:`LlmBusyError`.
  4. ``est_prompt + num_predict`` must fit the context window, checked before any
     network call.
  5. A ``length`` finish is reported as ``truncated`` and never auto-retried.

Nothing here hardcodes a host: the base URL and model are passed in by the
provider, which reads them from the environment.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass

import httpx

from aivan.llm import guard_config as cfg
from aivan.llm.cancellation import get_cancel_token
from aivan.llm.errors import (
    LLM_PROVIDER_CONNECTION_ERROR,
    LLM_PROVIDER_UNSUPPORTED_RESPONSE,
    LlmAbortedError,
    LlmBusyError,
    LlmContextOverflowError,
    LlmTimeoutError,
    LLMProviderError,
)

logger = logging.getLogger("aivan.llm.guard")

# Test-only transport injection. Production leaves this None and uses a real
# socket; tests install an ``httpx.MockTransport`` that streams synthetic Ollama
# JSONL so no live model is needed. Never set this in production code.
_test_transport: httpx.BaseTransport | None = None


def set_test_transport(transport: httpx.BaseTransport | None) -> None:
    global _test_transport
    _test_transport = transport


# ── Single-slot application concurrency gate (mirrors OLLAMA_NUM_PARALLEL=1) ──
_gate_lock = threading.Lock()
_gate: threading.BoundedSemaphore | None = None
_gate_size: int = 0


def _get_gate() -> threading.BoundedSemaphore:
    global _gate, _gate_size
    size = cfg.concurrency()
    with _gate_lock:
        if _gate is None or _gate_size != size:
            _gate = threading.BoundedSemaphore(size)
            _gate_size = size
        return _gate


def reset_gate() -> None:
    """Test hook: drop the cached semaphore so a new size takes effect."""
    global _gate, _gate_size
    with _gate_lock:
        _gate = None
        _gate_size = 0


def estimate_prompt_tokens(text: str) -> int:
    """Conservative prompt-token estimate (PRD 5.2).

    CJK: characters ~= tokens. Latin: words * 1.3. Take the larger, then apply a
    1.1 safety factor. Deliberately over-estimates so the budget check errs
    toward rejecting borderline-huge prompts rather than letting them through.
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if ord(c) >= 0x2E80)
    words = len(text.split())
    by_char = cjk + max(0, len(text) - cjk) / 4.0
    by_word = words * 1.3
    return int(max(cjk, by_word, by_char) * 1.1) + 1


@dataclass
class GuardResult:
    text: str
    truncated: bool
    prompt_tokens: int
    output_tokens: int
    duration_ms: float
    profile: str
    done_reason: str


class LlmTokenGuard:
    def __init__(self, provider_name: str = "ollama"):
        self.provider_name = provider_name

    # ── num_predict resolution: never amplify ───────────────────────────────
    def _resolve_num_predict(self, profile: cfg.LlmProfile, requested: int | None) -> int:
        hard = cfg.hard_max_num_predict()
        budget = min(profile.num_predict, hard)
        if requested is None:
            return budget
        effective = min(requested, budget)
        if requested > budget:
            logger.warning(
                "llm_guard num_predict amplification blocked: requested=%d capped=%d "
                "profile=%s hard_max=%d",
                requested, effective, profile.name, hard,
            )
        return max(1, effective)

    def _est_prompt_tokens(self, messages: list[dict]) -> int:
        joined = "\n".join(str(m.get("content", "")) for m in messages)
        return estimate_prompt_tokens(joined)

    def _compute_timeout(self, est_prompt: int, num_predict: int, profile: cfg.LlmProfile) -> float:
        computed = (
            cfg.load_time_buffer_s()
            + est_prompt / cfg.prompt_speed_tps()
            + num_predict / cfg.gen_speed_tps()
        ) * cfg.timeout_safety_factor()
        # Effective timeout = min(formula, per-profile ceiling, absolute backstop).
        # profile_timeout_ceiling already clamps to max_inference_timeout_s.
        return min(computed, cfg.profile_timeout_ceiling(profile))

    def stream_chat(
        self,
        *,
        base_url: str,
        model: str,
        messages: list[dict],
        profile: cfg.LlmProfile,
        requested_num_predict: int | None = None,
        response_format: str | None = "json",
        temperature: float | None = None,
    ) -> GuardResult:
        num_predict = self._resolve_num_predict(profile, requested_num_predict)
        est_prompt = self._est_prompt_tokens(messages)
        window = cfg.context_window()

        # ── Context-budget gate (before any network work) ───────────────────
        prompt_ceiling = int(window * cfg.max_prompt_tokens_ratio())
        if est_prompt > prompt_ceiling or est_prompt + num_predict > window:
            logger.warning(
                "llm_guard context overflow: est_prompt=%d num_predict=%d window=%d "
                "ratio_ceiling=%d profile=%s",
                est_prompt, num_predict, window, prompt_ceiling, profile.name,
            )
            raise LlmContextOverflowError(est_prompt, num_predict, window,
                                          provider=self.provider_name, model=model)

        timeout_s = self._compute_timeout(est_prompt, num_predict, profile)
        temp = profile.temperature if temperature is None else temperature

        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": profile.think,
            "options": {"temperature": temp, "num_predict": num_predict},
        }
        if response_format:
            body["format"] = response_format

        url = base_url.rstrip("/") + "/api/chat"

        # ── Concurrency gate: fail fast, never queue forever ────────────────
        gate = _get_gate()
        wait_budget = cfg.queue_wait_timeout_s()
        acquire_started = time.monotonic()
        if not gate.acquire(timeout=wait_budget):
            waited = time.monotonic() - acquire_started
            logger.warning("llm_guard busy: no free slot after %.1fs (concurrency=%d)",
                           waited, cfg.concurrency())
            raise LlmBusyError(waited, provider=self.provider_name, model=model)

        try:
            return self._run_stream(url, body, num_predict, est_prompt, timeout_s,
                                    profile.name, model)
        finally:
            gate.release()

    def _run_stream(self, url, body, num_predict, est_prompt, timeout_s,
                    profile_name, model) -> GuardResult:
        token = get_cancel_token()
        # Abort before we even open the socket if the caller already went away.
        if token is not None and token.is_aborted():
            raise LlmAbortedError(reason=token.reason or "client_disconnect",
                                  provider=self.provider_name, model=model)

        started = time.monotonic()
        deadline = started + timeout_s
        parts: list[str] = []
        done_reason = ""
        watchdog_reason = ""
        # read timeout bounds a *silent* hang (no chunks); the per-chunk deadline
        # bounds a slow-but-streaming run. connect is kept short.
        timeout = httpx.Timeout(connect=min(10.0, timeout_s), read=timeout_s,
                                write=timeout_s, pool=timeout_s)
        client_kwargs: dict = {"timeout": timeout}
        if _test_transport is not None:
            client_kwargs["transport"] = _test_transport
        try:
            with httpx.Client(**client_kwargs) as client:
                with client.stream("POST", url, json=body) as resp:
                    resp.raise_for_status()
                    watchdog_stop = threading.Event()

                    def close_at_deadline() -> None:
                        nonlocal watchdog_reason
                        while not watchdog_stop.wait(0.05):
                            if token is not None and token.is_aborted():
                                watchdog_reason = "aborted"
                                resp.close()
                                return
                            if time.monotonic() >= deadline:
                                watchdog_reason = "timeout"
                                resp.close()
                                return

                    watchdog = threading.Thread(
                        target=close_at_deadline,
                        name="aivan-llm-stream-watchdog",
                        daemon=True,
                    )
                    watchdog.start()
                    try:
                        for line in resp.iter_lines():
                            if not line:
                                pass
                            else:
                                chunk = _parse_line(line)
                                if chunk is not None:
                                    content = (chunk.get("message") or {}).get("content", "")
                                    if content:
                                        parts.append(content)
                                    if chunk.get("done"):
                                        done_reason = chunk.get("done_reason") or "stop"
                                        break
                            # Cooperative checks also catch cancellation between chunks.
                            if token is not None and token.is_aborted():
                                watchdog_reason = "aborted"
                                break
                            if time.monotonic() >= deadline:
                                watchdog_reason = "timeout"
                                break
                    finally:
                        watchdog_stop.set()
                        watchdog.join(timeout=0.2)

                    if watchdog_reason == "aborted":
                        self._log(profile_name, model, est_prompt, num_predict,
                                  started, done_reason="aborted", note=token.reason if token else "")
                        raise LlmAbortedError("".join(parts),
                                              reason=(token.reason if token else "") or "client_disconnect",
                                              provider=self.provider_name, model=model)
                    if watchdog_reason == "timeout":
                        self._log(profile_name, model, est_prompt, num_predict,
                                  started, done_reason="timeout", note=f"cap={timeout_s:.1f}s")
                        raise LlmTimeoutError(timeout_s, "".join(parts), reason="deadline",
                                              provider=self.provider_name, model=model)
        except httpx.TimeoutException as exc:
            self._log(profile_name, model, est_prompt, num_predict, started,
                      done_reason="timeout", note=type(exc).__name__)
            raise LlmTimeoutError(timeout_s, "".join(parts), reason="read_timeout",
                                  provider=self.provider_name, model=model) from exc
        except httpx.HTTPStatusError as exc:
            self._log(profile_name, model, est_prompt, num_predict, started,
                      done_reason="error", note=f"http_{exc.response.status_code}")
            raise LLMProviderError(LLM_PROVIDER_CONNECTION_ERROR, provider=self.provider_name,
                                   model=model, detail=f"http_{exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            if watchdog_reason == "aborted":
                raise LlmAbortedError("".join(parts),
                                      reason=(token.reason if token else "") or "client_disconnect",
                                      provider=self.provider_name, model=model) from exc
            if watchdog_reason == "timeout":
                raise LlmTimeoutError(timeout_s, "".join(parts), reason="deadline",
                                      provider=self.provider_name, model=model) from exc
            # ConnectError, network, protocol, DNS — anything transport-level.
            self._log(profile_name, model, est_prompt, num_predict, started,
                      done_reason="error", note=type(exc).__name__)
            raise LLMProviderError(LLM_PROVIDER_CONNECTION_ERROR, provider=self.provider_name,
                                   model=model, detail=type(exc).__name__) from exc

        if not done_reason:
            self._log(profile_name, model, est_prompt, num_predict, started,
                      done_reason="incomplete", note="eof_without_done")
            raise LLMProviderError(
                LLM_PROVIDER_UNSUPPORTED_RESPONSE,
                provider=self.provider_name,
                model=model,
                retryable=False,
                detail="eof_without_done",
            )

        text = "".join(parts)
        truncated = done_reason == "length"
        out_tokens = _approx_output_tokens(text)
        self._log(profile_name, model, est_prompt, num_predict, started,
                  done_reason=done_reason or "stop", truncated=truncated,
                  out_tokens=out_tokens)
        return GuardResult(
            text=text, truncated=truncated, prompt_tokens=est_prompt,
            output_tokens=out_tokens, duration_ms=(time.monotonic() - started) * 1000.0,
            profile=profile_name, done_reason=done_reason or "stop",
        )

    def _log(self, profile, model, est_prompt, num_predict, started, *,
             done_reason, truncated=False, out_tokens=0, note="") -> None:
        # Structured, append-only audit line. Never contains prompt content.
        duration_ms = (time.monotonic() - started) * 1000.0
        level = logging.WARNING if (truncated or done_reason in ("timeout", "aborted")) else logging.INFO
        logger.log(
            level,
            "llm_guard_call profile=%s model=%s est_prompt=%d num_predict=%d "
            "out_tokens=%d duration_ms=%.0f done_reason=%s truncated=%s note=%s",
            profile, model, est_prompt, num_predict, out_tokens, duration_ms,
            done_reason, truncated, note,
        )


def _parse_line(line: str) -> dict | None:
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _approx_output_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for c in text if ord(c) >= 0x2E80)
    return int(cjk + max(0, len(text) - cjk) / 4.0)
