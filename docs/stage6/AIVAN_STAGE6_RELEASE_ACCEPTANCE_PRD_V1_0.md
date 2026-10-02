# Acceptance Evidence Guide (Legacy Stage 6 Path)

Reconciled: 2026-10-02. This path is retained for existing links. Current product definition and acceptance are [Aivan Product Requirements](../AIVAN_PRODUCT_PRD.md), [MyAivan Web Requirements](../MYAIVAN_WEB_PRD.md) and [Acceptance Criteria](../ACCEPTANCE_CRITERIA.md).

## Purpose

Demonstrate the requested user flow with reproducible evidence. The former Stage 6 umbrella combined UI, every channel, corrections, capacity, cloud deployment and multiple sign-offs. It is not a source-authorized prerequisite chain for every Aivan delivery.

The complete Aivan product includes inquiry, quotation and order confirmation. The first MyAivan iteration has its own finite conversation/review/communication/backup scope. abcdYi retains its industry execution lifecycle. Do not substitute one scope's evidence for another or require every later capability before accepting a bounded result.

## Candidate and execution evidence

Record the exact branch/commit and actual dependency/API versions used, chosen database provider and designated simulated dataset, selected scenarios, run times, commands/user actions, expected and observed outcomes, and safe evidence references. Avoid secret values and unnecessary private data.

The two designated simulated DBs are valid acceptance sources. Use real application code and selected APIs; prove writes, readback and recovery from DB state after conversation switch/restart. Mock transport, skipped CI, pre-rendered screens or direct test-only state jumps do not prove the intervening workflow.

## Five consecutive MyAivan tests

The original web PRD requires five consecutive runs of its 20 cases. Retain that requirement. Record each run; keep failures and restart the sequence after a failed run is fixed. Do not assemble five unrelated historical passes or count a replay as an independent success.

File/image upload must be usable. Voice may be deferred. All IM channels use manual copy/send/confirmation. Configured email is explicitly confirmed; unconfigured email retains a clear copy fallback. A fallback pass is not a real-email-delivery pass. Do not expand these tests into mandatory automatic LINE sending or every live channel.

## Safety and state

Keep authentication, tenant/object permissions, trusted actors, idempotency, truthful approval/delivery status and secret protection. Stored business and process text is standard English except enterprise/user profiles; non-English input/output goes through the dynamic language module.

Useful event-correction, dependency-health and security tests remain valuable. Their presence does not make every additional feature mandatory for the initial UI. State a real defect's effect on the selected flow instead of promoting an audit observation into new product scope.

## Deployment is a distinct claim

A local or integration run does not prove deployment. A target-host claim needs the actual deployed revision and selected-path evidence there. Production change and outbound test messages require their specific authorization and applicable environment protections.

Do not make a full operational platform, extra signatory hierarchy, a particular cloud/DB product, production-customer data or all-channel receipts a blanket condition for functional acceptance. A `production_acceptance=false` preflight record must not be relabeled as live deployment evidence.

## Completion

Report scope, exact candidate, outcomes and limitations. The [traceability matrix](STAGE6_REQUIREMENT_TRACEABILITY.md) maps current outcomes to evidence. The [historical tracker](STAGE6_EXECUTION_TRACKER.md) preserves earlier engineering references without declaring them current product authority. This cleanup preserves all code/tests and does not authorize a release or deployment.
