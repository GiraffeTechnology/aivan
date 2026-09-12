# Aivan Delivery Stage Framework v1.1

Authority: [issue #96](https://github.com/GiraffeTechnology/aivan/issues/96). Product direction remains the seven-function loop in [#90](https://github.com/GiraffeTechnology/aivan/issues/90).

Establish staged delivery for abcdyi / Aivan without changing product direction or reducing engineering quality. Existing implementation is preserved; only delivery stages are separated.

## Stage 1 — Demonstrable Product

Objective:
Demonstrate the complete industrial order execution loop.

Scope:

RFQ Input
→ Requirement Structuring
→ Supplier Inquiry Draft
→ Supplier Reply Parsing
→ GLTG
→ Execution Recommendation
→ Human Approval

Acceptance:

- Complete user workflow;
- Data persistence works;
- Core integrations work;
- Demo can be executed end-to-end;
- Relevant tests pass.

Not blocking Stage 1:

- Enterprise scale deployment;
- Full observability;
- Advanced automation;
- Complete Digital Twin;
- Future platform capabilities.

## Stage 2 — Operational Readiness

Objective:
Support controlled pilot usage.

Additional scope:

- Multi-user operation;
- Permission management;
- Monitoring;
- Error recovery;
- Operational tooling.

## Stage 3 — Production Scale

Objective:
Commercial production deployment.

Additional scope:

- Performance;
- Reliability;
- Disaster recovery;
- Security hardening;
- SLA.

## Stage 4 — Enterprise / Institutional Grade

Objective:
Large-scale institutional deployment.

Additional scope:

- Compliance;
- External audit;
- Advanced governance;
- Institutional integration.

## Delivery Rule

Each stage has independent acceptance criteria.

A later stage MUST NOT block an earlier stage unless technically required for the current stage.

## Current Stage 1 Task

Complete and demonstrate the seven-function loop already defined in #90. The bounded work classification in #92 supports delivery; it does not replace the product baseline. Stage 1 completion is not a claim of controlled-pilot, production-scale, or institutional readiness.

Preserve existing implementation and relevant security, integrity, and test protections. Classify current work as KEEP, FINISH-NOW, FREEZE-LATER, or REMOVE; REMOVE applies only to unsupported active instructions or demonstrably harmful/obsolete material, not a broad implementation rollback.


## Current Work Classification

| Category | Current work | Treatment |
| --- | --- | --- |
| KEEP | Existing RFQ handling, structuring, drafts, reply parsing, GLTG integration, recommendation, human approval, UI, persistence, tenant/auth protections, valid tests and safeguards | Preserve useful implementation and engineering quality. |
| FINISH-NOW | Demonstrate the Stage 1 loop through the UI and backend, persist and read back its business data, fix fractional lead-time and recommendation-currency defects, validate required integrations and approval | Work through focused implementation PRs and record actual tests/demo evidence. |
| FREEZE-LATER | Enterprise scaling, full observability, advanced automation, complete Digital Twin, and future platform capabilities not technically needed for Stage 1 | Preserve existing work; exclude unrelated expansion from Stage 1 acceptance. |
| REMOVE | Unsupported active instructions that demand later-stage completion before Stage 1, obsolete duplicate gates and inaccurate completion claims | Retire the conflicting instruction, not useful code or necessary security evidence. |

## Stage 1 Execution and Evidence

- Objective: complete and demonstrate the existing #90 RFQ-to-human-approval loop, not redefine it.
- Affected repository: Aivan, with required interfaces supplied by the existing component repositories.
- Minimum files: only files implementing a demonstrated defect or missing step and their focused tests; this framework PR changes documentation only.
- Validation command: each focused PR records the exact repository-supported test and demo commands for its changed path. Relevant integration checks must exercise the required real components; skipped jobs or mocks are not substitutes for the end-to-end demo.
- Exit evidence: a reproducible user-flow demonstration, successful backend execution, persisted business data and readback, core integration results, and relevant passing tests.

Current Stage 1 task: #90 implementation and end-to-end demonstration, supported by the bounded classification task #92. The UI and correctness slices may proceed independently when they have no technical dependency. This framework does not declare Stage 1 complete.

## Preserve Quality and Stage Boundaries

The additional scope of Stages 2–4 does not remove authentication, permissions, tenant isolation, approval controls, integrity protections, or error handling technically needed for Stage 1. No existing tests, CI checks, security safeguards, runtime code, or deployment configuration are disabled by this document.

Freeze a completed stage by recording its delivered scope, tested revision, and evidence. Do not erase valid implementation or prohibit necessary defect fixes. Stage 1 demonstrates the product; controlled pilot and commercial production claims require their respective stages. This document does not itself order a deployment or cancel separately authorized work.

Only the explicitly approved four stages are introduced here. Agents must not invent additional acceptance gates or use later-stage observations as current blockers without a technical dependency.
