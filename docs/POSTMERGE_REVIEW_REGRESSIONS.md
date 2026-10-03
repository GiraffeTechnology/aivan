# PR 129 post-merge review regressions

## Scope and reproduced baseline

The four findings in [review comment 5973800719](https://github.com/GiraffeTechnology/aivan/pull/129#issuecomment-5973800719) were checked against the merged `myaivan-web` baseline `4f640f9dbb046a0202d8d31186f506977146dfc0`.

- An authenticated buyer or supplier could restore canonical message bodies from other same-role conversations in the same case. New API regression tests failed for both roles; authorized internal-role controls passed.
- The delegated click handler treated the order-confirmation button's `data-case-id` as case-card navigation. The runtime regression observed zero human-confirmation prompts and no order-confirmation POST.
- With category-only or material-only requirements, an omitted criterion admitted unrelated suppliers. Both filtering regressions failed on the baseline.
- The remote supplier client read only the first page. A relevant supplier after the first 100 records was absent from the routing inputs.

## Changes

External conversation reads are restricted by tenant, case, authenticated actor, business role, and active participant membership before canonical bodies are resolved. Authorized internal roles keep their existing view. The browser's delegated navigation selectors now match case cards specifically, leaving action buttons to their action handlers and native keyboard behavior.

Supplier matching retains the existing OR semantics for criteria actually supplied by the caller. An unspecified criterion and an empty supplier material entry cannot create a match. With neither criterion supplied, the complete active catalog remains available.

The selected provider's `total`, `limit`, and `offset` contract is followed until every page has been read. Tenant/auth headers are retained on every request. Invalid pagination, a changing reported total, repeated IDs, a non-progressing page, cross-tenant rows, or a later-page failure raise a context error instead of returning a partial candidate list. Retrying re-reads the catalog; offset pagination is not claimed to provide a cross-request database snapshot.

## Verification

- Final local Python suite: 1,175 passed, 3 existing optional integration skips; coverage 83.23%.
- All nine existing UI runtime scripts passed, including actual delegated confirmation, cancel, nested-click, button-keyboard, and case-card navigation regressions.
- Whole-repository Ruff, affected-source Mypy, Bandit high-severity scan, and existing module budgets passed.
- An additional local check used the actual selected provider's authenticated FastAPI route, repository, and SQLite storage through an in-process HTTP transport. With 105 synthetic active suppliers, category-only and material-only queries selected the relevant second-page records; the unrestricted query returned all 105. Inactive and other-tenant rows remained excluded. This is a real-code API contract check, not a live-network or production acceptance claim.

The existing exact-file Semgrep finding for the conversation runtime test was re-reviewed: its two filesystem reads still use literal `app.js` and `index.html` paths. Only that finding's exact SHA and explanation changed; scanner rules and thresholds remain unchanged.

No deployment, real commercial send, new credentials, database migration, or cross-repository source archive upload is part of this patch. `myaivan-web` remains a separate release branch and must not merge into `main`.
