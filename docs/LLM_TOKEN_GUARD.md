# Local-LLM Token Guard

Code-level protection for the single-CPU production Ollama box. The guard makes
it **structurally impossible** for any code path to send an unbounded or
uncancellable request to the local model. It is not a prompt convention and not
an optional parameter — every local inference is routed through
`LlmTokenGuard`.

## Why

The production box is a 4 vCPU / 16 GB CPU-only host running Ollama with
`OLLAMA_NUM_PARALLEL=1`. Without an output cap and a real cancel path, a single
`think=true` request with no `num_predict` was observed generating >1500 tokens
for up to ~12 minutes at ~250% CPU — effectively freezing the box. The guard
removes that failure mode.

> **Model reference — reconcile before merge.** The timeout/queue defaults
> (`LLM_QA_MAX_TIMEOUT_S=90`, `LLM_QUEUE_WAIT_TIMEOUT_S=100`, per-profile
> ceilings) are tuned against the **9B** model per the Token-Guard PRD
> (`qwen3.5:9b`, Q4_K_M, ~5.3 tok/s) and the parallel stress test, where a
> ~268-token reply took ~62s. However the AIVAN application default is
> `OLLAMA_MODEL=qwen3.5:2b` (from earlier work). These disagree: if the box
> actually serves **2b**, replies are much faster and the 90s ceiling is
> generous; if it serves **9b**, 90s is the intended snug bound for `qa_*`. The
> guard is correct either way (it only ever *bounds*), but the deployed
> `OLLAMA_MODEL` and the measured speed must be reconciled. This doc describes
> the 9B tuning basis.

## Guarantees (hard invariants)

1. **Bounded output** — every request body carries `options.num_predict`, always
   `= min(requested, profile budget, LLM_HARD_MAX_NUM_PREDICT)`. It is never
   enlarged; an amplification attempt is clamped down and logged.
2. **Streamed + real cancel** — the call is always `stream=true`. On timeout or
   client disconnect the stream is closed, so Ollama **stops generating** (not
   just the client giving up).
3. **Wall-clock circuit-break** — `timeout = min(token-budget formula, LLM_MAX_INFERENCE_TIMEOUT_S)`.
   `LLM_MAX_INFERENCE_TIMEOUT_S` (default **90s**) is an absolute ceiling: any
   single inference is force-aborted at that point regardless of budget. The
   default was raised from 60s to 90s after a production stress test showed a
   legitimate ~268-token reply completing in ~62s (see *Timeout chain* below).
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

### Per-profile wall-clock ceilings

The wall-clock ceiling is **per profile**, not a single global 90s (which would
make `reasoning`/`reasoning_max` unusable — at ~5 tok/s, 90s yields only
~350–400 output tokens, so a 1024/2048-token budget could *never* complete and
every reasoning call would end as a partial-text timeout). Defaults are sized so
each profile can realistically emit its budget on the 9B CPU box:

| profile         | num_predict | budget @≈5 tok/s | ceiling (env)                       |
|-----------------|-------------|------------------|-------------------------------------|
| `qa_short`      | 256         | ~51s             | `LLM_QA_MAX_TIMEOUT_S` = **90s**     |
| `qa_standard`   | 512         | ~102s            | `LLM_QA_MAX_TIMEOUT_S` = **90s**     |
| `reasoning`     | 1024        | ~205s            | `LLM_REASONING_TIMEOUT_S` = **240s** |
| `reasoning_max` | 2048        | ~410s            | `LLM_REASONING_MAX_TIMEOUT_S` = **480s** |

`qa_*` stay tight for interactive responsiveness (a `qa_standard` reply that
runs past 90s is still force-truncated — but the observed natural stop is ~268
tokens / ~62s, so real traffic completes). `reasoning*` get headroom to finish.
Every ceiling is clamped by the **absolute backstop** `LLM_MAX_INFERENCE_TIMEOUT_S`
(default **480s**): no single inference may ever exceed it, whatever the profile.

> AIVAN's live pipeline maps every task to `qa_short`/`qa_standard`
> (`TASK_PROFILE`), so in production every real inference is bounded at 90s. The
> reasoning profiles exist for explicit opt-in and now complete rather than
> silently truncating.

## Timeout chain (verified)

Effective per-inference wall-clock = `min(budget formula, per-profile ceiling,
absolute backstop)`, with nothing shorter undercutting it:

| stage | value | note |
|-------|-------|------|
| budget formula | `(load_buffer + est_prompt/prompt_tps + num_predict/gen_tps) * safety` | can propose minutes |
| per-profile ceiling | 90 / 240 / 480s | interactive vs reasoning |
| absolute backstop | `LLM_MAX_INFERENCE_TIMEOUT_S` = 480s | final hard limit |
| **effective timeout** | `min(formula, ceiling, backstop)` | e.g. **90s** for qa_* |
| httpx `read` / `write` / `pool` | = effective | bounds a *silent* hang |
| httpx `connect` | `min(10s, effective)` | connection setup only |
| per-chunk deadline | `start + effective` | bounds a slow-but-streaming run |
| queue wait (gate) | `LLM_QUEUE_WAIT_TIMEOUT_S` = 100s | separate, *before* inference starts |

- `AIVAN_LLM_TIMEOUT_SECONDS` (30s) **no longer governs local Ollama** — it now
  applies only to the external, approval-gated providers. Local inference is
  bounded solely by the guard.
- **Upstream timeout must cover queue wait + inference, not just inference.** A
  queued request waits up to `LLM_QUEUE_WAIT_TIMEOUT_S` *before* its inference
  starts, so set nginx `proxy_read_timeout` and any OpenClaw/runtime request
  timeout to **≥ `LLM_QUEUE_WAIT_TIMEOUT_S` + (max profile ceiling in use) + margin**.
  For the qa-only live pipeline that is `100 + 90 = 190s` → use ≥ ~210s; if
  reasoning profiles are enabled, size against their ceilings. If the upstream
  fires first the client disconnects and the guard aborts cleanly (Ollama stops,
  user gets a retry) — safe, but a successfully-queued reply is lost.

## Concurrency & queue behavior

`OLLAMA_NUM_PARALLEL=1` means the model does **one** inference at a time;
everything else queues. The guard's app-level gate mirrors this:

- `LLM_CONCURRENCY=1` — one active inference. **Do not raise on 4C16G**: a 9B
  model on CPU has no spare CPU/RAM for real parallel gain.
- `LLM_QUEUE_WAIT_TIMEOUT_S=100` (~one inference) — a **2nd** concurrent request
  waits for the slot and succeeds; a **3rd+** exceeds the wait and fails fast with
  `LlmBusyError` (friendly retry) instead of piling up. This deliberately caps
  the effective depth at ~2 and avoids a deep serial queue.

### Production stress test (4C16G, qwen3.5 9B, 1024-token cap; natural stop ~268 tok)

| concurrent | success | wall time | slowest | throughput | min free RAM |
|-----------:|--------:|----------:|--------:|-----------:|-------------:|
| 1 | 1/1 | 62.1s | 62.1s | 4.32 tok/s | 7.00 GiB |
| 2 | 2/2 | 105.3s | 105.3s | 5.09 tok/s | 6.77 GiB |
| 4 | 4/4 | 213.3s | 213.3s | 5.03 tok/s | 6.50 GiB |

Findings: only 1 request runs in parallel (rest queue serially), so throughput
stays ~5 tok/s regardless of concurrency; at 4-deep the management plane (new SSH
connections) briefly degraded; no OOM or inference errors, and all services
recovered afterward. The guard's fast-fail at 100s queue wait is what keeps the
system out of that 4-deep region in production — excess requests are rejected
cleanly rather than queued for 160–213s.

Recommended production posture: **best = 1 in-flight; acceptable = 2 (2nd
queues); reject beyond that.** These defaults encode exactly that.

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
