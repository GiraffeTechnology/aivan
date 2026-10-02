# Aivan Acceptance Criteria

Reconciled: 2026-10-02. Authority: the source requirements and explicit product-owner corrections mapped in [source reconciliation](PRODUCT_SOURCE_RECONCILIATION.md). These criteria describe the evidence required for the claimed scope; they are not a claim that the current candidate passed.

## 1. State the claim before testing

Record the branch and exact commit, the user flow being delivered, selected DB provider and designated simulated dataset, service/API versions, configuration profile without secrets, and commands or user actions actually executed. Use one coherent candidate/component combination; do not assemble a pass from unrelated revisions.

The first MyAivan UI and the full Aivan business flow have distinct observable scope. The full product includes order confirmation. abcdYi's production/QC/logistics/sign-off lifecycle belongs to its industry application. A deployment claim additionally needs evidence from the actual target environment. No label silently substitutes for another.

## 2. Full Aivan business-flow criteria

| ID | Required outcome | Evidence |
| --- | --- | --- |
| A-01 | Buyer inquiry, supplier reply and operator instruction enter the correct case/participant flow | Actual UI/API input, persisted source and identity/case linkage; supplier reply does not become a new buyer inquiry |
| A-02 | Requirements and missing fields are inspectable and correctable | Structured output and original evidence, explicit unknowns, persisted correction and next step |
| A-03 | Relevant suppliers/products/history are read from the selected private-domain DB | Real provider/API read and record references; no conversation-memory or hard-coded fixture substitute |
| A-04 | Supplier inquiry is a reviewable draft and replies become comparable quotations | Recipient/channel/purpose/body, prices/currencies/quantity/terms and source references; unknowns remain unknown |
| A-05 | GLTG/GPM-dependent work uses the selected real API contracts | Requests/results attributable to the candidate, actual options and explanations; dependency failure shown without invented substitute results |
| A-06 | Quotation and recommendation preserve known facts and distinguish inference | Relevant prices, lead-time estimates, risk notes and actual available candidate count; no fabricated third option |
| A-07 | Review, rejection, revision and authorized communication behave correctly | No outbound action before authorization; copy is not send; manual IM and configured-email evidence are accurately distinguished |
| A-08 | Human order confirmation is part of the delivered flow | Selected quotation, authorized confirmation, persisted order/business status and audit readback; no independent formal-contract/signature/version prerequisite |
| A-09 | History and process state are durable and recoverable | DB writes/readback plus continuation after conversation switch and service restart; no chat-context dependency |
| A-10 | Selected-path safety and integrity hold | Authentication, tenant/object permissions, replay/idempotency, input/file safety and truthful error-state checks relevant to the changed functions |

The exact chosen business API may already implement these outcomes; this document does not mandate new endpoints, tables, columns or an additional state machine merely to match its wording.

## 3. MyAivan first web iteration

Use [MyAivan Web Requirements](MYAIVAN_WEB_PRD.md), including all 20 original UI cases and the latest DB-backed persistence/recovery criteria. File and image input must work; only voice may be a placeholder. Welcome/Start Working and the conversation/review/input layout must be demonstrated, not replaced by operations screens.

Retain the original five-consecutive-run requirement. Each run covers the applicable scope, records PASS/FAIL and actual evidence, and preserves failure records. After a failure and fix, restart the sequence. Never count replayed idempotent requests or a skipped case as another successful independent run.

A clearly unconfigured email adapter with working copy fallback satisfies that stated fallback path. It cannot be reported as real email delivery. All IM channels remain review/copy/manual-send/confirmation in this iteration, including LINE and WhatsApp.

## 4. Database and dependency evidence

The two designated simulated databases are accepted product-test/acceptance sources, including when populated from real local data. Record their identifiers using the user's actual designations; do not invent names, present them as production-customer histories, or demand production customers as a condition of acceptance.

Use the application and chosen DB/API service for process changes and readback. Test the designated database source or sources selected for the delivery and record the adapter/profile used. Both designated sources are eligible; this does not create a requirement to run every scope on both. Demonstrate provider replaceability by the agreed mapping/configuration boundary, with correct isolation and recovery; do not demand support for every arbitrary database product or schema.

Keep these distinctions explicit:

- **Simulated dataset through real application/API/DB execution:** valid functional acceptance evidence.
- **Mock transport or stubbed dependency response:** useful unit/contract/preflight evidence; it does not show the real API integration ran.
- **Skipped CI step:** not executed and not a pass, even if its enclosing job is green.
- **Pre-rendered screen or direct test-only state mutation:** not evidence that the intervening user workflow executed.
- **Target-host deployment test:** evidence only for the observed candidate/profile; no inference from an unrelated local run.

DB unavailability must not silently switch business truth to chat memory or fake persistence. Successful state changes have committed records; uncertain outcomes remain visibly uncertain. A service result used in a decision is retained with its relevant source/provenance.

## 5. Language and DB-content checks

Verify standard-English workflow and interaction. Non-English input must be dynamically translated by `giraffe-language-skill` before product workflow; requested non-English output uses the same module. Except enterprise/user profile information, no non-English textual business content may enter DB history, process state, messages, drafts, events, audit or metadata. Check nested/free-text fields and the narrow profile exception; do not add raw-language/side-store exemptions. Existing records require an authorized translation/migration plan, not deletion.

## 6. GLTG iteration checks

For a delivery that claims the trade-and-processing-time iteration, apply [the GLTG integration specification](GLTG_BEHAVIORAL_STATISTICAL_MODEL_ITERATION_PRD.md): four source-defined inventory/response scenarios, implemented formula tests, nonnegative/monotone quantiles, explanation and source mapping, and client regressions.

Full DAG simulation, new optional tables and long-term statistical calibration are not prerequisites for the rule-based iteration. Do not claim empirical P80/P90 coverage without the corresponding measured calibration. A document-only formula is not an executed model.

## 7. Scope and safety limits

Retain real human authorization, data isolation, secure handling and correct state. Do not remove runtime guards, tests or CI checks merely to obtain green status. If an existing guard encodes a superseded product rule, describe the exact conflict and implement its correction in an authorized code change, preserving the safety purpose.

Do not impose additional formal-contract gates, full observability/enterprise platforms, a fixed cloud/DB vendor, all live channels, unrelated statistical research, mandatory production-customer data or additional signatory chains as product acceptance prerequisites. Existing repository checks and unavailable paid scanning services must be reported accurately as engineering/check availability; they do not independently redefine the product.

Deployment or external test sending requires authorization for that action. Operational protections apply to the target actually being changed. Functional acceptance on the designated simulated DB does not require first completing a production-host deployment, and acceptance does not itself authorize one.

## 8. Evidence record and completion report

For each criterion record: source requirement, candidate/component revisions, scenario, dataset/provider, actions/command, expected and observed result, pass/fail/not-run/blocked, safe evidence reference, and any limitation. Exclude secrets and unnecessary private business content.

Report exactly what passed and what remains. An absent UI, order confirmation, DB recovery or actual dependency call cannot be marked complete because related code exists. Conversely, valid functional execution using designated simulated DB data cannot be rejected solely because the data is simulated. No new product stage or requirement may be introduced while reporting completion.
