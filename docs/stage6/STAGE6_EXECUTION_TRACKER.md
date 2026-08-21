# Stage 6 execution tracker

Baseline reconciled 2026-08-10: `main@61e456688952cda6e09574b33413b4eb1f84aac3`.

## 6A — release gates and automated evidence

- [x] cover all seven event-correction blocker codes
- [x] add five-run preflight evidence runner
- [x] add requirement-to-evidence traceability matrix
- [x] full local regression and GitHub CI
- [x] Claude Code cross-review

Evidence: PR #58 established the runner and digest-only evidence; PR #59 added
candidate CI execution; PR #60 passed 6/6 CI and Claude Code cross-review before
merge. These automated gates are not production acceptance.

## Stage 7B–7E candidate under review

The `codex/stage7b-myaivan-workbench` candidate adds a trusted HttpOnly UI
session, role projections, workbench APIs/UI, digest-only message evidence,
schema validation and migration orchestration, readiness/metrics, security
headers and CodeQL. Local evidence is 797 passed / 2 skipped with 81.52%
coverage, plus Ruff, 12-file Mypy and Bandit gates. This is a candidate, not a
merged release or production acceptance.

## Required before candidate freeze

- [ ] Stage 5B MyAIVAN shared-Core API (candidate implements the workbench
  aggregate API; separately paginated child collections and attachment storage
  remain)
- [ ] Stage 5C Email/LINE controlled adapters and real receipts
- [ ] Stage 5D MyAIVAN operator UI (responsive candidate implemented; real
  device end-to-end and attachment upload recovery remain)
- [ ] current-main transfer card and attachment placeholder evidence

## Production acceptance

- [ ] approved CTYun maintenance window and verified backup
- [ ] migrations previewed/applied/re-previewed
- [ ] all non-China paths verified through `abcdyi-sin`
- [ ] AIVAN ports 443/8443 proved unchanged
- [ ] UI/RFQ/roles/approval/OpenClaw/Email/LINE/Relay/Reversal/Token Guard 5/5
- [ ] real mobile WeChat guided-relay round trip 5/5
- [ ] backup restore, dependency failure, and rollback drills
- [ ] product/engineering/operations/supervisor sign-off

Unchecked items are not delivered and must not be reported as passed.

