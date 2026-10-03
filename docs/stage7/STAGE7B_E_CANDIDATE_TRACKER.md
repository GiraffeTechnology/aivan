# Historical MyAivan Workbench Candidate Record

Reconciled: 2026-10-02. Original status date: 2026-08-20. This is historical implementation evidence, not a current product baseline, live topology statement or acceptance gate.

## Preserved candidate assets

The prior candidate reported trusted HttpOnly sessions, CSRF handling, server-controlled roles, tenant-scoped case/workbench APIs, audit exports, digest/reference message evidence, dependency readiness/metrics and migration/predeployment tooling. It reported 797 tests passed, 2 skipped, 81.52% coverage, Ruff, 12-module Mypy and Bandit checks plus a 390 x 844 browser walkthrough. Those are historical claims to verify at their own revision, not results newly executed for this cleanup.

The earlier reported deployed revision was `b8def41adb54533f311e569b358a93d22ed6e565` on `myaivan-web`. Its August host/route/profile observations are not assumed current. Operational details belong in the authorized target inventory, not a product definition.

## Differences from the reconciled delivery target

- A sidebar operations workbench does not replace Welcome/Start Working and the conversation/review/input layout.
- Metadata-only attachment placeholders do not meet first-iteration file/image input.
- A fixed local SQLite profile is an implementation choice, not the only permitted DB provider. Business facts and process state must use the chosen dynamic DB truth boundary and recover from it.
- Direct LINE delivery and unsupported WhatsApp do not define the first web iteration; all its IM channels use manual copy/send/confirmation.
- Fixed generated locale catalogs do not replace dynamic language-skill translation or authorize non-English business DB storage.
- Broader corrections, capacity, signing, observability and provider catalog work is preserved without becoming a prerequisite for unrelated first-UI functions.

## Current follow-up

Use [Acceptance Criteria](../ACCEPTANCE_CRITERIA.md) to assess the actual selected candidate and [Scope Preservation Inventory](../SCOPE_PRESERVATION_INVENTORY.md) to keep expanded work. Record gaps without deleting code, weakening isolation or inventing completion. Deployment remains an independently authorized action; this tracker does not execute it.
