# Delivery Handoff Guide (Legacy Stage 7 Path)

Reconciled: 2026-10-02. Current product and acceptance authority are the [Aivan PRD](../AIVAN_PRODUCT_PRD.md), [MyAivan PRD](../MYAIVAN_WEB_PRD.md) and [Acceptance Criteria](../ACCEPTANCE_CRITERIA.md). The historical Stage 7 program is not a replacement product definition.

## 1. Deliver the actual user outcome

Aivan is the Giraffe Agent frontend for inquiry, quotation and order confirmation. MyAivan is its web version, not a separate workflow system. Its first UI uses Welcome/Start Working, conversation/review/input, real file/image handling, reviewed drafts, manual IM, configured-email confirmation/fallback and Markdown backup.

Use the dynamic private-domain DB for history and process state, recoverable after conversation switch/restart. GLTG/GPM remain API dependencies. The designated simulated DBs are valid for real functional acceptance. No separate formal-contract confirmation gate is added before production.

Standard English is the work/interaction language; non-English I/O is translated dynamically by `giraffe-language-skill` before workflow or for display. Only enterprise/user profiles may contain non-English DB content. Do not add raw/audit/metadata exceptions.

## 2. Preserve safety and useful engineering

Keep tested session authentication, trusted identities, tenant/object permissions, idempotency, controlled outbound actions, correct approval/delivery semantics, event lineage and safe logging. Preserve correction, health, metrics, migration and evidence tooling where useful. Expanded or unselected code is frozen and inventoried, not deleted or silently disabled.

A plugin harness must not turn internal status or model text into an unauthorized external message. Approval authorizes the reviewed action; it is not proof of sending. Copy and human relay confirmation are distinguishable from provider delivery. Unknown outcomes must remain visible.

File/image upload is required for the first UI. Existing metadata-only placeholders are an implementation limitation, not an acceptable redefinition of that goal. Apply minimal necessary upload access/type/size/rendering protection; a whole object-storage/scanning platform is not automatically required.

## 3. Evidence and handoff

For the requested scope, supply the exact candidate/branch, selected component contracts, designated DB source/provider, actual tests/user actions, results, safe evidence links and unresolved limitations. Retain the source-defined five-run first-UI tests. Test real API/DB writes/readback/recovery for integration claims; do not count skipped steps, mocks, direct state jumps or historical passes as the current workflow.

An existing operations dashboard is not evidence for the required conversation experience. An RFQ-to-approval demo is not the full order-confirmation product. A first-UI pass is not abcdYi lifecycle completion. Keep these claims precise without inventing mandatory stages between them.

## 4. Authorized deployment operations

A merge, docs proposal or preflight does not authorize production mutation or external messages. When deployment is requested, observe the current target and use the actual authorized profile and rollback/migration safety needed for that change. Protect existing services, credentials and data. Apply the CTYun/bridge restrictions only to operations in that environment; do not change them through this cleanup.

The existing quarantined workflow records no deployment. Existing preflight/predeployment evidence with `production_acceptance=false` remains that evidence class. Do not relabel it.

The earlier blanket requirements for all Stage 7A-E work, all real channels, an institutional signatory chain, all locale catalogs, a particular GitHub paid feature, full capacity/observability programs and a fixed database profile are not independent product acceptance criteria. CI must be green before merge; failed or unavailable checks must be reported and handled within the authorized workflow, not hidden or bypassed.

## 5. Retired authority and historical evidence

Prior Stage 7 text referred to August candidates and a larger operations program. Their commits and evidence remain in Git history and [the historical candidate tracker](STAGE7B_E_CANDIDATE_TRACKER.md). Its source code and tests are preserved. The record must not be treated as proof of today's runtime or as permission to recreate withdrawn gates.

A final report states what is implemented, tested, merged and deployed separately. It does not require production-customer data to accept valid designated-simulation execution and does not claim business completion from document edits alone.
