# Tenant and Idempotency Guardrails

## Tenant resolution (fail closed)

`aivan.tenancy.resolver.resolve_tenant` resolves a tenant in priority order and
refuses to guess:

1. Explicit tenant_id from authenticated / request context.
2. Tenant from a verified channel-account binding.
3. Tenant from verified project / procurement_case ownership.
4. Tenant from an operator-confirmed mapping.
5. Otherwise: **fail closed** (`TenantResolutionError`,
   code `TENANT_RESOLUTION_REQUIRED`).

Two verified sources that disagree raise `TenantMismatchError`
(`TENANT_MISMATCH`) — cross-tenant access is rejected rather than silently
choosing one.

### Test-mode fallback (never in production)

A fallback tenant is used **only** when `AIVAN_TEST_MODE` is truthy *and*
`AIVAN_TEST_TENANT_ID` is configured. It emits a warning and log line. With
`AIVAN_TEST_MODE=false` (or unset) no fallback is used.

### Service calls

`resolve_service_tenant` is used for AIVAN → giraffe-db and AIVAN → GLTG v2
calls. It honors `AIVAN_TENANT_ID` / `GIRAFFE_DB_TENANT_ID`, else the test-mode
tenant, else fails closed. The old silent defaults (`server_e2e`,
`tenant_default`) are removed. `persist_rfq_gltg_graph` writes **nothing** when
the tenant cannot be resolved in production.

## Idempotency

Inbound events (OpenClaw / IM / email / webhook retries) are deduplicated by:

```
source + channel + channel_account_id + conversation_id + message_id
```

stored in `processed_inbound_events` (unique `idempotency_key`). The first
successful processing records the result; a duplicate replays it with **no** new
projects, RFQs, drafts, or execution events. Events with no message id **and** no
conversation id are processed without dedup (they lack safe identity).

Duplicate **approvals** are guarded separately: a draft is created
`pending_approval`, and re-approving an already-handled draft returns HTTP 409 —
no double-send.

### Recommended idempotency keys for future high-risk operations

| Operation | Key |
| --- | --- |
| inbound event | `source + channel + channel_account_id + conversation_id + message_id` |
| operator confirmation | `tenant_id + confirmation_type + source_event_id + confirmed_payload_hash` |
| RFQ creation | `tenant_id + procurement_case_id + requirement_snapshot_hash` |
| supplier invitation draft | `tenant_id + project_id + rfq_id + supplier_id + target_channel + message_template_hash` |
| GLTG run request | `tenant_id + procurement_case_id + rfq_id + supplier_id + quote_id + request_payload_hash` |
| decision option | `tenant_id + procurement_case_id + quote_comparison_snapshot_hash + strategy_hash` |
| comparison snapshot | `tenant_id + procurement_case_id + sorted_quote_ids_hash + gltg_run_ids_hash + pricing_input_ids_hash` |
| approval event | `tenant_id + draft_id + approval_actor + approval_action + approval_payload_hash` |

## Database note

AIVAN creates its schema via `Base.metadata.create_all` (no Alembic). The
`processed_inbound_events` table + unique index apply automatically to fresh
databases; the repository additionally guards against races at the application
level (get-or-record with `IntegrityError` fallback).
