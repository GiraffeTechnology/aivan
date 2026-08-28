# ADR 0003: AIVAN control-plane and runtime safety boundary

Status: Accepted for Stage A
Date: 2026-08-28

## Context

AIVAN was described and partly implemented as a standalone trade-execution
worker with local business facts and test fallbacks. The approved product role
is instead the P0 monitoring and human-takeover control plane. `giraffe-db` is
the authority for all non-QC business facts; GLTG owns lead-time results;
OpenClaw owns channel connectivity; giraffe-language-skill owns translation
generation; humans retain final commercial responsibility.

## Decision

Production AIVAN declares and validates these exact invariants before mutable
state is initialized:

- `AIVAN_PRODUCT_ROLE=monitoring_takeover_control_plane`;
- `AIVAN_BUSINESS_FACT_AUTHORITY=giraffe-db`;
- `AIVAN_LOCAL_STATE_SCOPE=control_audit_cache_only`;
- human approval remains mandatory;
- mock LLM, mock OpenClaw, mock search, mock marketplace, mock GPM, stub
  suppliers, fake HTTP transports, fabricated histories, and automatic external
  model calls are rejected;
- code generation, code execution, repository writes, and Git operations are
  prohibited runtime capabilities.

The packaged CLI no longer launches developer test processes. Tests are run by
the repository toolchain outside the product runtime. GPM binds to loopback by
default and a non-loopback bind requires configured authentication.

Existing local business tables are not approved facts. Until Stage D replaces
their reads/writes with an accepted giraffe-db API/SDK contract, production
context construction fails closed. Stage A does not implement that cutover.
Local persistence is allowed only for control state, audit evidence, or an
explicit cache/projection with source version, TTL, invalidation, and rebuild
semantics.

## Runtime denylist scope

The denylist applies to `src/aivan` and every production entry point, including
the API, standalone GPM process, CLI, scheduled jobs, and integration clients.
It excludes repository-owned developer tooling under `tests/` and `scripts/`,
which is never imported or launched by the packaged runtime. CI statically
rejects `subprocess`, `os.system`, `os.popen`, `eval`, `exec`, `compile`, shell
execution, and Git-library imports in `src/aivan`.

## Consequences

- A misconfigured production process fails before database initialization.
- Readiness reports each policy invariant without exposing configuration values.
- Local/test environments retain explicit mocks for deterministic tests.
- Stage B must add monitoring closure, Stage C takeover state machines, and
  Stage D the real giraffe-db consumer cutover. This ADR does not claim those
  stages complete.

## Rollback

Rollback restores the previous application SHA but must not weaken the denylist
or re-enable production mocks. If the policy prevents startup, the safe state is
not-ready/no side effects until configuration or code is corrected and audited.
