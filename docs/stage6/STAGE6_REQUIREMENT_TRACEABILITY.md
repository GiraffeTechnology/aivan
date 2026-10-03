# Current Requirement-to-Evidence Map

Reconciled: 2026-10-02. This replaces the former Stage 6 umbrella-gate matrix. Source IDs refer to [Product Source Reconciliation](../PRODUCT_SOURCE_RECONCILIATION.md). No row below asserts that the current implementation passed.

| Requirement | Source | Relevant existing assets to inspect | Acceptance evidence |
| --- | --- | --- | --- |
| Inquiry/requirement/supplier-reply handling | A1 sections 1-4; C1 | Shared invoke, RFQ and domain services; unified/role tests | Actual correct case/participant flow and DB records |
| Private-domain facts and process state | C1 | DB clients, repositories, GPM persistence contract | Real selected provider/API writes/readback and conversation/restart recovery on the two designated simulated DBs |
| Quotation and options | A1 sections 1, 9-10; L1 | Supplier response, buyer options, GLTG/GPM clients | Grounded price/terms/options, real API output and uncertainty |
| Order confirmation | C1; A2 sections 5, 8 | Shared order integration used by Aivan/industry app | Human confirmation and persisted selected-order state; no extra formal-contract gate |
| Conversation-first MyAivan UI | W1 sections 6-11 | Existing workbench assets and tests are reusable, not proof of the required layout | Welcome/Start Working, three-area page, right/left alignment |
| File/image input and backup | W1 sections 11, 13, 15, 19-20 | Upload/content-reference/export implementation and selected storage | Usable supported files/images and Markdown backup with case/status/audit |
| Draft review and channel behavior | A1 sections 2, 4; W1 sections 5, 10, 12, 17 | Approval, relay and email adapters | All IM manual; configured email confirmation or truthful fallback; no false sent status |
| Five consecutive UI runs | W1 sections 21, 24 | Existing runner may be reused where it covers the right scope | Five actual runs of original 20 cases, failures retained; no skipped-as-passed |
| English workflow and DB | C3 | Language integration and canonical/write-validation boundaries | Dynamic translation before workflow; English non-profile DB data; narrow profile exception |
| Selected-path safety | A1 section 2; A2 role/permission workflow | Tenant, role, idempotency, auth and file/security tests | Changed-path authorization, isolation and integrity verified |
| GLTG factor iteration when claimed | L1 sections 6-13 | API clients and factor/model tests | Four scenario cases, executable formulas, quantile checks and provenance |
| Target-host deployment when claimed | Specific operation authorization | Predeployment/migration/deployment tooling | Actual target revision, scoped health/user-flow outcome and applicable operational protection |

Tests mentioned are assets to inspect, not automatic proof. Record exact candidate, actual command/actions, expected/observed outcome and safe evidence link. A provider's simulated data is accepted; a fake service response is only mock-test evidence. No new approval hierarchy, enterprise platform or fixed DB/cloud vendor is created by this matrix.
