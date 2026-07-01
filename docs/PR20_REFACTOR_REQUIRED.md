# PR20 — Refactor Required (Do Not Merge)

**PR:** #20 — *feat: persist structured RFQ intake into temporary inquiry sheets*
**Status:** open, draft. **Decision: do not merge as-is.**

## 1. Why PR20 should not be merged as-is

PR20 introduces a parallel "temporary inquiry sheet" intake/grouping layer
(`InquirySheet` / `InquiryMessage`, deterministic RFQ text structuring, and
same-inquiry matching) that persists inbound RFQ state *outside* the canonical
project/procurement flow. Merging it now would:

- create a **second source of truth** for inbound RFQ state that overlaps with
  the existing project / requirement / execution-event model and with
  giraffe-db's canonical procurement-case store;
- add an intake path that is **not yet reconciled** with the PR19/PR22 cleanup
  guarantees in this PR (tenant fail-closed, inbound-event idempotency, and
  LLM-output validation);
- risk **duplicate or divergent records** for the same inbound event, since the
  temporary sheets and the idempotency ledger were designed independently.

## 2. Which architecture boundary it violates

- **giraffe-db owns canonical business facts, lineage, and audit.** A durable
  intake-grouping store in AIVAN blurs that boundary; grouping/matching results
  should resolve to canonical procurement-case identity, not a private
  long-lived AIVAN table.
- **AIVAN owns workflow orchestration**, not a competing canonical data model.
  Temporary in-flight grouping is acceptable, but it must be clearly transient
  and must not become an authoritative record.

## 3. What refactor is required

1. Make the intake layer **explicitly ephemeral**, or fold its grouping result
   into the existing project / procurement-case identity rather than a new
   authoritative table.
2. Route inbound sheet creation through the **same idempotency key** added in
   this cleanup (`build_inbound_idempotency_key`) so retries do not create
   duplicate sheets/messages.
3. Enforce **tenant fail-closed** on any sheet persistence using
   `aivan.tenancy.resolver`.
4. Ensure any LLM-based structuring uses the hardened gateway
   (`llm_complete_json` fail-closed) and does not treat empty/invalid output as
   success.
5. Define reconciliation with giraffe-db canonical records (who owns the fact,
   what is lineage, what is audit).

## 4. Which tests must pass before reconsideration

- Duplicate inbound event → **one** sheet and **one** project (idempotent).
- Uncertain match creates a `temporary_unconfirmed` sheet and **never** merges
  into an existing confirmed sheet.
- Sheet persistence **fails closed** when no tenant is resolvable in production.
- No outbound message is generated from intake without human approval.
- Existing `pytest -q`, `compileall`, and this cleanup's targeted suites remain
  green.

Do not modify PR20 code as part of the cleanup PR beyond this note.
