# Local-LLM Token Guard

Code-level protection for the single-CPU production Ollama box. The guard makes
it **structurally impossible** for any code path to send an unbounded or
uncancellable request to the local model. It is not a prompt convention and not
an optional parameter — every local inference is routed through
`LlmTokenGuard`.

## Why

Production runs `qwen3.5:2b` on Ollama on a 4 vCPU / 16 GB CPU-only host with
`OLLAMA_NUM_PARALLEL=1`. Without an output cap and a real cancel path, a single
`think=true` request with no `num_predict` was observed generating >1500 tokens
for up to ~12 minutes at ~250% CPU — effectively freezing the box. The guard
removes that failure mode.

## Guarantees (hard invariants)

1. **Bounded output** — every request body carries `options.num_predict`, always
   `= min(requested, profile budget, LLM_HARD_MAX_NUM_PREDICT)`. It is never
   enlarged; an amplification attempt is clamped down and logged.
2. **Streamed + real cancel** — the call is always `stream=true`. On timeout or
   client disconnect the stream is closed, so Ollama **stops generating** (not
   just the client giving up).
3. **60s circuit-break** — `timeout = min(token-budget formula, LLM_MAX_INFERENCE_TIMEOUT_S)`.
   `LLM_MAX_INFERENCE_TIMEOUT_S` (default **60s**) is an absolute ceiling: any
   single inference is force-aborted at 60s regardless of budget.
4. **Client-disconnect abort (AbortController)** — when the frontend user
   interrupts or closes the page, the API layer aborts a cancel token carried
   into the worker thread via `contextvars`; the guard checks it between chunks
   and closes the stream.
5. **Single-slot concurrency** — an app-level semaphore (`LLM_CONCURRENCY=1`)
   mirrors `OLLAMA_NUM_PARALLEL=1`; queue overflow fails fast with `LlmBusyError`
   after `LLM_QUEUE_WAIT_TIMEOUT_S`, never queues forever.
6. **Context budget** — `est_prompt + num_predict <= LLM_CONTEXT_WINDOW` and
   `est_prompt <= window * ratio`, checked **before** any network call; overflow
   raises `LlmContextOverflowError` (no silent prompt truncation).
7. **No auto-retry on truncation** — `done_reason=length` is surfaced as
   `truncated=true`; the guard never enlarges the budget or retries.
8. **Append-only audit** — every call logs `profile, est_prompt, num_predict,
   out_tokens, duration_ms, done_reason, truncated`; truncation / timeout / busy
   are WARNING level. Log lines never contain prompt content.

## Call profiles

Business code selects a **profile** by intent (never free-forms `think`/budget):

| profile         | think | num_predict | temperature | use                              |
|-----------------|-------|-------------|-------------|----------------------------------|
| `qa_short`      | false | 256         | 0–0.3       | classification / extraction      |
| `qa_standard`   | false | 512         | 0–0.3       | default business answers         |
| `reasoning`     | true  | 1024        | 0.2         | moderate reasoning               |
| `reasoning_max` | true  | 2048        | 0.2         | complex reasoning (explicit)     |

> Note: under the 60s hard cap on a ~5 tok/s CPU box, large budgets
> (`reasoning`/`reasoning_max`) can hit the circuit-break and return `truncated`.
> Server stability wins over completion — by design.

## Configuration

All knobs live in `.env` (`.env.example` / `deploy/aivan.production.env.example`).
The Ollama endpoint always comes from `OLLAMA_BASE_URL`; **no host is ever
hardcoded** in code, tests, logs, or docs (CI scans for direct `/api/chat`,
`/api/generate`, port `11434`, and routable IP literals).

## Where it lives

- `src/aivan/llm/guard.py` — `LlmTokenGuard` (the only place that opens the
  Ollama socket).
- `src/aivan/llm/guard_config.py` — env + profiles + the 60s ceiling.
- `src/aivan/llm/cancellation.py` — `CancelToken` + contextvar propagation.
- `src/aivan/llm/providers/ollama_provider.py` — builds messages, selects a
  profile, and classifies the streamed result.
- `src/aivan/api/main.py` — `/invoke` disconnect watcher that aborts the token.

## Tests

- `tests/test_llm_token_guard.py` — the 8 adversarial classes above.
- `tests/test_invoke_disconnect_abort.py` — API-level disconnect → abort.
- `tests/test_llm_guard_ci_bypass.py` — no-bypass / no-hardcoded-host CI guard.
- `tests/test_ollama_provider.py`, `tests/test_ollama_typed_errors.py` — streamed
  provider contract + typed failures.
