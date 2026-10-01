# Aivan Repository Instructions

## Scope and ownership

- Aivan owns the user-facing seven-step delivery flow: RFQ input, requirement
  structuring or clarification, supplier inquiry draft, supplier reply parsing,
  GLTG evaluation, execution recommendation, and human approval.
- This repository owns Aivan orchestration, user workflow, UI, approval and
  recovery behavior, and its HTTP consumers for giraffe-db and GLTG.
- GLTG owns canonical lead-time calculation. giraffe-db owns private business
  facts, persistence APIs, tenant isolation, and provider-side idempotency.
- Do not copy GLTG calculations into Aivan or access giraffe-db business tables
  directly. Integrate both dependencies through their real, versioned APIs.
- Do not modify abcdYi from this repository task.

## Current defect register

Work against these existing-delivery defects without inventing additional
product stages or release gates:

- A01: replace production stub/local business context with the real giraffe-db
  context API.
- A02: make graph persistence recoverable, idempotent, readable back, and
  visibly distinct from local pending state.
- A03: expose the current execution recommendation and reject action in the
  operator workbench.
- A04: keep rejection, revision, regeneration, and concurrent case state
  transitions consistent.
- A05: preserve fractional GLTG values through DTOs, persistence, ranking, API,
  and UI serialization.
- A06: do not invent earliest dates, critical paths, or missing GLTG values.
- A07: send verified supplier and case identity instead of presenting a
  requirement-level baseline as a supplier evaluation.
- A08: bind currency explanations to the selected quote and never compare
  unlike currencies without verified conversion evidence.
- A09: deduplicate by stable business identity and do not make unsupported
  fastest or reliability claims.
- A10: align the GPM consumer and provider contract, including authenticated
  discovery and actual persistence semantics.
- A11: do not invoke GLTG for status-only or unrelated events; preserve clear
  recovery behavior for every real entry point.

## Implementation rules

- Reproduce each defect before fixing it. Add a regression that fails for the
  original behavior and passes for the corrected behavior.
- Prefer the smallest change that closes the actual defect. Reuse existing
  implementations and pull-request assets instead of recreating them.
- Keep tenant, actor, correlation, idempotency, and business identifiers across
  service boundaries. Never substitute a static tenant for authenticated
  request context.
- A successful HTTP call is not persistence proof. Where the workflow claims a
  fact is saved, verify it through the provider API and preserve returned IDs.
- Distinguish authentication, authorization, not-found, conflict, invalid input,
  unavailable service, definite failure, and indeterminate commit outcomes.
- Local test doubles may isolate error paths, but they do not prove real API
  interoperability or the end-to-end delivery flow.
- Keep counterparty-facing actions behind the existing human approval boundary.
  Tests must not send to real customers or suppliers.

## Evidence and delivery discipline

- Report exact commands, exit codes, passed/failed/skipped counts, database type,
  and the exact commit and tree under test.
- Historical results, pull-request descriptions, skipped jobs, and author claims
  are inputs to verify, not current passing evidence.
- Do not obtain green checks by deleting tests, weakening assertions, lowering
  thresholds, adding `continue-on-error`, switching required paths to mocks, or
  disabling required functionality.
- Do not add new approval layers, governance documents, architecture programs,
  future-stage requirements, or unrelated release gates.
- Do not expose credentials, private endpoints, infrastructure parameters,
  internal task routing, AI-session references, or generated-by markers in
  repository files, logs, commits, pull requests, or public documentation.
- Preserve unrelated dirty changes. Do not rewrite Git history, force-push,
  merge protected branches, deploy production, or perform real outbound actions
  unless the user explicitly authorizes that action.

## Required validation

- Run focused regression tests for every changed defect path.
- Run the relevant broader Python, TypeScript, static analysis, and build checks
  before handing off a candidate.
- For real integration claims, exercise Aivan against actual HTTP services for
  giraffe-db and GLTG and read persisted facts back through APIs. Record mock,
  local-only, permission-blocked, and unexecuted checks accurately.
