# Event Impact and Immutable Correction Specification

Reconciled: 2026-10-02. Historical implementation scope: Stage 5A, originally based on `7838c38393f9f42c6c88a218b7f888d6923c0a8c`. This is a preserved engineering specification, not an additional prerequisite for every first-web-iteration function. Current product authority is [Aivan Product Requirements](../AIVAN_PRODUCT_PRD.md).

## Purpose and boundary

Provide an inspectable correction path without deleting or overwriting original business history. Preview effects, authorize a safe supported reversal, or record a compensation requirement when automatic reversal is unsafe. Keep the existing implementation/tests; unselected expansion is frozen rather than removed.

This specification covers `case_state` and `requirement_json.strategy` materialized-state reversal, not a universal inverse executor. It does not authorize external messages, automatic LINE sending, deployment or database migration. It does not redefine file/image input as a placeholder.

## Existing API contract

- `GET /api/events/{event_id}/impact`: read-only tenant-scoped preview of the source, affected state, intended restoration, later/derived events, warnings, blockers and impact digest.
- `POST /api/events/{event_id}/reverse`: supported automatic reversal, or explicit `compensation_only` evidence recording.

Both use trusted authentication, tenant/actor/role and correlation context. An arbitrary request-body role grants no permission. Cross-tenant events are not exposed. The existing implementation grants impact visibility through `VIEW_AUDIT` and reversal through `REVERSE_EVENT`, currently admin-only. Auditors may inspect but cannot reverse.

The reversal request includes a nonempty standard-English reason and `Idempotency-Key`. A fresh server-side impact check prevents reliance on stale UI state. The successful response identifies the ledger/correction event and whether the response is an idempotent replay.

Error semantics include missing key/reason, authentication/authorization/not-found, unsafe reversal and conflicting reuse of an idempotency key. Preserve the implemented error identifiers and API compatibility when changing code.

## Supported reversal safety

Automatic reversal requires a visible Case, supported before/after fields, unchanged current materialized value, no later conflicting mutation, no unresolved derived effects, and no prior correction of the source. The existing blocker identifiers are:

- `event_already_corrected`
- `correction_events_cannot_be_reversed`
- `case_not_found`
- `no_supported_materialized_state`
- `materialized_state_diverged`
- `later_mutation_exists`
- `derived_events_exist`

When unsafe, `compensation_only=true` records the need for manual compensation without falsely changing state to “restored.” Original events remain intact. Corrections retain source relationships and append their own audit evidence.

## Persistence and language

Existing fields include `derived_from_event_id`, `payload_digest` and `correction_status`, with a tenant/source/idempotency-scoped `event_reversals` ledger. Keep source/correction references, actor, role, reason, trace, impact and before/after provenance. Replay returns the original result without duplicate events; a key reused for a different source fails.

The chosen private-domain DB remains the business history/process system of record. A provider can map these semantics without adopting one mandatory physical schema. Stored textual business content, including correction reasons/audit descriptions, is standard English; the enterprise/user-profile exception does not apply to event payloads. Existing non-English records need an authorized translation/migration plan, not deletion.

## Validation

Preserve tests for supported reversal, each blocker, compensation without state mutation, immutable original history, tenant isolation, auditor/admin permissions, key conflicts, replay and secret-safe errors. Changes to applicable storage/migrations must be tested against the selected provider, including repeatability and readback. The two designated simulated DBs are valid data sources.

Preview and backup/recovery protections apply when a migration is actually authorized. A code/docs PR is not deployment permission. No new requirement to complete this entire correction program before unrelated UI functions may be inferred from the legacy Stage 5A label.
