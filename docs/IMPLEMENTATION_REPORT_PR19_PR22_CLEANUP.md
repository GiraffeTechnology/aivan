# Implementation Report — PR19 / PR22 Cleanup

## Summary

Cleanup follow-up for already-merged **PR19** (native Ollama LLM provider) and
**PR22** (GLTG v2 RFQ graph persistence). This change hardens three defect
areas without adding new product features:

1. **Ollama empty / invalid JSON handling** — invalid or empty model output is
   now a typed, manual-review failure instead of a silent empty-object success
   or a fabricated Mock assessment.
2. **Tenant fallback** — AIVAN no longer silently guesses a tenant for
   giraffe-db / GLTG v2 service calls; it fails closed outside explicit test
   mode.
3. **Idempotency** — duplicate / retried inbound events no longer create
   duplicate projects, RFQs, drafts, or execution events.

PR20 and PR21 are **not** merged. See `PR20_REFACTOR_REQUIRED.md` and the
architecture docs for their status.

## PR19 cleanup: Ollama empty JSON

- **files changed:**
  - `src/aivan/llm/errors.py` (new) — typed `LLMProviderError` + normalized
    error codes.
  - `src/aivan/llm/providers/ollama_provider.py` — classify empty / whitespace /
    null / `{}` / malformed / array / scalar / timeout / connection-error /
    text-around-JSON, with conservative retry.
  - `src/aivan/llm/gateway.py` — `llm_complete_json` fails closed on provider
    error; Mock fallback only in explicit mock / `AIVAN_TEST_MODE`.
- **behavior before:** `safe_json_loads(content, {})` turned an empty/invalid
  body into `{}` treated as success; the gateway silently substituted a
  fabricated `MockLLMProvider` assessment on any error.
- **behavior after:** empty/invalid output raises `LLMProviderError` with a
  specific `error_code` (`LLM_EMPTY_RESPONSE`, `LLM_INVALID_JSON`,
  `LLM_PROVIDER_UNSUPPORTED_RESPONSE`, `LLM_PROVIDER_TIMEOUT`,
  `LLM_PROVIDER_CONNECTION_ERROR`) and `manual_review_required=True`. Empty
  bodies retry at most once. The exception message never contains the model
  name or prompt. All nine `llm_complete_json` callers already wrap the call and
  degrade to deterministic rule-based parsing (not a fabricated assessment).
- **tests:** `tests/test_ollama_empty_json_cleanup.py` (14),
  existing `tests/test_ollama_provider.py` / `tests/test_llm_gateway.py` still
  pass.

## PR22 cleanup: tenant fallback

- **files changed:**
  - `src/aivan/tenancy/resolver.py` (new) — `resolve_tenant` (priority order +
    mismatch rejection + fail-closed) and `resolve_service_tenant`.
  - `src/aivan/integrations/giraffe_db.py` — `persist_rfq_gltg_graph` resolves
    the tenant via `resolve_service_tenant` instead of defaulting to
    `"server_e2e"`.
  - `src/aivan/integrations/gltg.py` — GLTG v2 simulation resolves the tenant
    instead of defaulting to `"tenant_default"`.
  - `tests/test_gltg_client.py` — v2 facade test now sets an explicit tenant
    (reflecting the new fail-closed contract).
- **behavior before:** business writes to giraffe-db and GLTG v2 reads silently
  fell back to a hard-coded shared tenant (`server_e2e` / `tenant_default`) when
  no tenant was configured.
- **behavior after:** resolution order is explicit → verified channel binding →
  verified case ownership → operator-confirmed → **fail closed**. Two disagreeing
  sources raise `TenantMismatchError`. A test-mode fallback tenant is used only
  under `AIVAN_TEST_MODE` with a configured `AIVAN_TEST_TENANT_ID`, and it emits
  a warning. In production with no tenant, giraffe-db persistence raises
  `TenantResolutionError` and writes nothing.
- **tests:** `tests/test_tenant_resolution_cleanup.py` (14).

## PR22 cleanup: idempotency

- **files changed:**
  - `src/aivan/db/models/execution.py` — new `ProcessedInboundEvent` table with a
    unique `idempotency_key`.
  - `src/aivan/db/models/__init__.py` — register the new model.
  - `src/aivan/db/repositories/inbound_event_repo.py` (new) —
    `build_inbound_idempotency_key` + get-or-record `InboundEventRepository`.
  - `src/aivan/execution/rfq_execution.py` — `create_rfq_from_event` now checks
    the idempotency ledger first and replays the stored result on a duplicate,
    otherwise records the processed event after the inner workflow.
- **behavior before:** a retried inbound event re-ran the full workflow, creating
  duplicate supplier drafts and execution events every time.
- **behavior after:** the idempotency key is
  `source + channel + channel_account_id + conversation_id + message_id`. A
  duplicate replays the original `RFQExecutionResult` with **no** new drafts or
  events. Events lacking any identity (no message id and no conversation id) are
  processed without dedup rather than being wrongly collapsed. Duplicate draft
  approvals are already rejected with HTTP 409 (no double-send).
- **tests:** `tests/test_inbound_idempotency_cleanup.py` (7).

### Database migration note

AIVAN has no Alembic migration framework; the schema is created via
`Base.metadata.create_all` (`src/aivan/db/session.py`). The new
`processed_inbound_events` table and its unique index are therefore applied
automatically to fresh databases — no separate migration file is required. For
an existing/long-lived database, create the table (and the repository's
get-or-record path additionally guards against races at the application level).

## PR20 status

- **do not merge:** yes.
- **refactor required:** see `PR20_REFACTOR_REQUIRED.md`.

## PR21 status

- **do not merge:** yes.
- **docs updated:** `CURRENT_ARCHITECTURE_STATUS.md`, `INTEGRATION_BOUNDARIES.md`,
  `LLM_PROVIDER_AND_OUTPUT_VALIDATION.md`, `TENANT_AND_IDEMPOTENCY_GUARDRAILS.md`.

## Test results

- `pytest -q`: **492 passed, 2 skipped**
- `compileall src tests`: **OK**
- targeted `ollama or empty_json or invalid_json`: **17 passed**
- targeted `tenant or fallback`: **46 passed**
- targeted `idempot or duplicate or retry`: **7 passed**

## Known limitations

- Tenant is not yet a first-class column on AIVAN's local models; it is resolved
  for outbound service calls (giraffe-db / GLTG). A future change should thread a
  verified tenant onto `Project` / inbound events so `resolve_tenant`'s
  channel-binding and case-ownership sources are populated from persisted data.
- The idempotency ledger stores the serialized `RFQExecutionResult` to replay
  duplicates; very large results are stored as JSON. A future change could store
  a reference and re-read canonical state from giraffe-db.
- GLTG v2 now requires an explicit tenant; deployments enabling
  `GLTG_API_VERSION=v2` must set `AIVAN_TENANT_ID`.

## Follow-up PRs required

- PR20 refactor (intake ownership / boundary) per `PR20_REFACTOR_REQUIRED.md`.
- Thread verified tenant onto persisted inbound events and projects.
- Extend idempotency keys to supplier-invitation, GLTG-run, decision-option, and
  comparison-snapshot operations per the recommended key list.
