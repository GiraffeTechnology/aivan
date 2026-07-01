# Integration Boundaries

| System | Owns | Must NOT |
| --- | --- | --- |
| **AIVAN** | Workflow orchestration, inbound event handling, draft generation, human-approval gating | Compute lead-time math locally; own canonical business facts; silently guess a tenant; send outbound without approval |
| **GLTG** | Lead-time & risk simulation (`/v1`, `/v2/lead-time/simulate`) | — |
| **giraffe-db** | Canonical business facts, lineage, audit (buyers, procurement cases, RFQs, GLTG runs, pricing inputs, decision options, comparison snapshots) | — |
| **OpenClaw** | IM/email channel execution | Send messages that were not human-approved |

## AIVAN → GLTG

- AIVAN builds GLTG requests from RFQ context and maps responses into DTOs.
- `GLTG_API_VERSION=v1|v2` selects the contract. **v2 requires an explicit
  tenant** (`AIVAN_TENANT_ID`); it no longer defaults to a placeholder tenant.
- On error, AIVAN raises `GLTGUnavailableError` — no local fallback math.

## AIVAN → giraffe-db

- Pre-PO RFQ/GLTG graph persistence is opt-in
  (`AIVAN_PERSIST_GIRAFFE_DB_GRAPH=true`, `GIRAFFE_DB_BASE_URL` set).
- The tenant is resolved via `aivan.tenancy.resolver.resolve_service_tenant` and
  **fails closed** if unresolved in production — business facts are never written
  under a guessed tenant.
- giraffe-db remains the canonical fact/lineage store; AIVAN records references,
  not a competing source of truth.

## AIVAN → OpenClaw

- Outbound drafts are created `pending_approval`; a human approval transitions
  them and triggers send. Re-approving an already-handled draft returns HTTP 409.

## Inbound events (OpenClaw / IM / webhook)

- Deduplicated by
  `source + channel + channel_account_id + conversation_id + message_id`
  (`processed_inbound_events`). Retries replay the original result with no new
  side effects.
