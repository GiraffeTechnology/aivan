# Current Architecture Status (post PR19 / PR22 cleanup)

This document reflects the merged architecture **after** the PR19/PR22 cleanup.
It is a prerequisite for reconsidering PR21; PR21 must not be merged until
documentation and implementation are consistent.

## System roles / boundaries

1. **AIVAN** owns workflow orchestration and channel-facing execution. It does
   **not** own canonical business facts and does **not** compute lead-time math
   locally.
2. **GLTG** is the lead-time / risk evaluator. AIVAN calls GLTG over HTTP and
   must never substitute a locally computed estimate; on GLTG failure it raises
   `GLTGUnavailableError`.
3. **giraffe-db** is the canonical business-fact, lineage, and audit store.
4. **OpenClaw** owns IM/email channel execution. Outbound messages require human
   approval before send.

## Model / provider posture

- **Qwen3.5 may be the default model in some components, but Giraffe is not a
  Qwen ecosystem product.** Provider-specific clients (Ollama, OpenAI, Anthropic,
  Google, DeepSeek, Qwen, Mock) live behind the `LLMProvider` adapter interface
  and are selected via `AIVAN_LLM_PROVIDER`.
- LLM output must be structured and validated. Empty/invalid output is a typed
  `LLMProviderError` (manual review), never a false success. See
  `LLM_PROVIDER_AND_OUTPUT_VALIDATION.md`.

## Safety guarantees now enforced

- **AIVAN must not silently fall back to local lead-time math** — GLTG failures
  surface as errors.
- **Tenant fallback fails closed** outside explicit test mode. See
  `TENANT_AND_IDEMPOTENCY_GUARDRAILS.md`.
- **OpenClaw / IM outbound messages require human approval** before send; drafts
  are created in `pending_approval` and a second approval of the same draft is
  rejected (409).
- **Duplicate callbacks and retries are idempotent** for inbound events.

## Not merged

- **PR20** (temporary inquiry sheets) — refactor required; see
  `PR20_REFACTOR_REQUIRED.md`.
- **PR21** (GLTG behavioral statistical model PRD) — documentation-first; keep
  unmerged until the PRD and implementation are consistent with this status.
