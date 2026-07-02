# Tenant & Inbound-Idempotency Guardrails (post-PR29)

Salvaged from PR27 and merged onto the PR29 architecture. This documents the
final behavior on current `main`, not PR27's original (stale) design.

## 1. Fail-closed tenant resolution

Single home: `src/aivan/utils/tenant.py` (the PR29 unified resolver, now
fail-closed). No module invents its own tenant fallback; GLTG v2 and giraffe-db
graph persistence both call `resolve_service_tenant(context=...)`.

Resolution priority:

1. `AIVAN_TENANT_ID`
2. `GIRAFFE_DB_TENANT_ID`
3. `GIRAFFE_TENANT_ID`
4. verified channel binding / project (passed by callers that have it)
5. operator-confirmed tenant (passed by callers that have it)
6. **fail closed** → `TenantResolutionError` (code `TENANT_RESOLUTION_REQUIRED`)

- There is **no** `server_e2e` / `tenant_default` production fallback anymore.
- Two verified sources that disagree → `TenantMismatchError`
  (`TENANT_MISMATCH`); cross-tenant access is rejected, never reconciled.
- Test-mode fallback is allowed **only** when `AIVAN_TEST_MODE=true` **and**
  `AIVAN_TEST_TENANT_ID` is set; it warns and is never available in production.
  The test suite sets both in `tests/conftest.py`.

## 2. Inbound event idempotency

Model `ProcessedInboundEvent` (`processed_inbound_events`), repo
`InboundEventRepository`.

- `build_inbound_idempotency_key(source, channel, channel_account_id,
  conversation_id, message_id)` → stable `inb_<sha256[:48]>`, or `None` when the
  event has neither a message id nor a conversation id (such events are processed
  **without** idempotency rather than being wrongly collapsed together).
- `create_rfq_from_event()` checks the ledger **before** any side effect:
  - duplicate → replay the stored `RFQExecutionResult`; no new project/RFQ/
    draft/execution event is created.
  - first time → process, then record the result keyed by the idempotency key.
- The unique `idempotency_key` column makes a concurrent duplicate collide at the
  DB level (`IntegrityError` → return the existing row).
- Duplicate approval remains a 409 / no double-send (draft approval state machine
  is unchanged from PR29).

## 3. Ollama typed invalid-output failures

`src/aivan/llm/errors.py` (`LLMProviderError` + codes) and a hardened
`OllamaProvider`.

- Empty / whitespace / `null` / `{}` → `LLM_EMPTY_RESPONSE`
  (one bounded retry for empty, then raise).
- Malformed/truncated JSON → `LLM_INVALID_JSON`.
- Valid JSON that isn't an object (array/scalar) → `LLM_PROVIDER_UNSUPPORTED_RESPONSE`.
- Timeout / connection → `LLM_PROVIDER_TIMEOUT` / `LLM_PROVIDER_CONNECTION_ERROR`.
- Text-around-JSON is recovered when it contains a valid object; otherwise typed error.
- Error messages never include the model name, prompts, or provider bodies.

Previously `main` returned `{}` for empty/garbage output — a false success that
PR29 telemetry would count as a real local call. Now such output is a typed
failure.

## 4. Interaction with PR29 policy (preserved)

- **No mock fallback** except `AIVAN_LLM_PROVIDER=mock`. A local/external
  provider failure (including the new typed `LLMProviderError`) fails closed:
  the gateway emits `provider_ok=false` telemetry and raises
  `LocalModelUnavailableError`; callers downgrade to deterministic extraction.
  PR27's test-mode gateway mock fallback was **intentionally dropped** — enabling
  it would let a garbage local model look like success and invalidate the
  benchmark's integrity guarantee.
- **External model APIs stay off by default and approval-gated** (unchanged).
- Benchmark mapping: typed invalid output → `provider_ok=false` →
  `local_call_status = local_call_failed` (measured capability, not an integrity
  breach), `external_api_called=false`, `fell_back_to_mock=false`.
- Production local model remains **qwen3.5:2b**.
