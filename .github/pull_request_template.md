## Summary

<!-- Describe the delivery change and its audit/PRD stage. -->

## Verification

- [ ] Required CI checks passed.
- [ ] Test evidence and known skips are recorded below.
- [ ] Security, tenant, idempotency, and migration impact were reviewed where applicable.

## Codex / Claude Code cross-review

The default single-write-account workflow requires one agent to implement and
the other to review the PR and CI evidence. GitHub account approval is not a
gate because both agents operate through the same repository owner account.

- Implementing agent: <!-- Codex or Claude Code -->
- Cross-review agent: <!-- Claude Code or Codex -->
- Cross-review evidence: <!-- task/session link, review comment, or commit -->

If cross-review is intentionally skipped, link the project supervisor's
explicit authorization and state its scope:

- Single-agent exception authorization: <!-- required when cross-review is skipped -->

## Test evidence

<!-- Commands, pass/skip counts, and external-service prerequisites. -->
