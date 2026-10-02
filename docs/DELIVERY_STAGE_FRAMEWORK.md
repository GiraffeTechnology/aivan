# Bounded Delivery Guidance

Reconciled: 2026-10-02. Current product scope is defined in [Aivan Product Requirements](AIVAN_PRODUCT_PRD.md), with [observable acceptance](ACCEPTANCE_CRITERIA.md).

## Product target and finite work

Aivan is the Giraffe Agent frontend for inquiry, quotation and order confirmation. MyAivan is its web version. Deliver a finite requested user flow, integrate the components needed by that flow, test it, demonstrate the result and record the exact delivered scope.

The earlier seven-function RFQ-to-human-approval loop and four-stage framework in issues #90/#96 are historical planning references. They are neither the complete current product definition nor independent authorization for new operational, institutional or enterprise prerequisites. Legacy Stage 5/6/7 and Stage A-D names identify historical engineering work, not an ordered chain that must all finish before the current user-facing result can be accepted.

## Preserve and converge

- Preserve useful implementation, source-defined tests, data isolation, authorization and integrity protections.
- Finish defects and missing integration actually needed for the requested flow.
- Freeze unrelated expanded work with its source revision and inventory. Do not delete it, refactor it away, silently disable it or promote it into a new requirement.
- Report observations and proposed later improvements separately from demonstrated failures of the current scope.
- Never use AI authorship or complexity alone as a reason to condemn or remove code.

## Evidence

Identify the branch/candidate, chosen DB provider and designated simulated database, actual service contracts, test actions and limitations. Functional acceptance may use the two designated simulated DBs. It must execute actual application/API paths and persist/read back state, including recovery; mocks, skipped jobs and static screens do not establish that result.

Retain the original MyAivan five-run UI requirement at its actual scope. A completed UI iteration, a full inquiry-to-order-confirmation flow, an abcdYi lifecycle run and a target-host deployment must each be reported at the scope actually proved. This is a distinction between claims, not a new set of mandatory product stages.

## Operations and branch separation

`myaivan-web` remains independently released and must never merge into `main`. CI must be green before a merge; neither a docs change nor a passing check authorizes a merge or deployment.

Deployment and external test sending require authorization for those actions, and relevant environment-specific safeguards remain in force. Full operational platforms, production-customer datasets, every live channel, long-term model calibration or a formal-contract signature gate do not become default prerequisites for a functional product delivery.
