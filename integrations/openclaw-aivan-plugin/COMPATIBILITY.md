# AIVAN OpenClaw compatibility matrix

| Artifact | Supported version | Verification basis |
|---|---:|---|
| AIVAN Core | 0.3.x | `/api/health` and Stage 3 contract tests |
| AIVAN OpenClaw plugin | 0.3.x | package, manifest, build and Gateway harness |
| AIVAN trade-salesperson SKILL | 0.3.x | shared `intent-boundary.json` contract |
| OpenClaw Gateway | 2026.6.8 through 2026.7.x | published SDK build plus synchronized fork source contract |
| Node.js | >=22.19.0 | OpenClaw baseline engine requirement |

The current OpenClaw source baseline is `GiraffeTechnology/openclaw` commit
`1e06fd443033b8aa2fd638ee66b7fdad1168b8aa` (package version `2026.7.2`),
synchronized from `openclaw/openclaw/main` on 2026-08-03. Because `2026.7.2`
is not yet published to npm, the reproducible package build uses the latest
available compatible SDK package `2026.6.8` and separately verifies the current
fork source contract.
Versions outside the rows above require a new build, install, inspect and E2E run;
they are not assumed compatible.

All three AIVAN artifacts use the same minor version. A `0.3.x` SKILL must not be
paired with a plugin older than `0.3.0`, because the earlier plugin does not expose
the formal six-tool Gateway contract or the shared intent boundary.

## Stage 3 identity limitation

Stage 3 uses one static OpenClaw service identity per plugin process. The trusted
identity headers are populated from `AIVAN_TENANT_ID`, `AIVAN_ACTOR_ID`,
`AIVAN_ROLE_CONTEXT`, `AIVAN_CONVERSATION_ROLE`, and `AIVAN_EXECUTION_MODE`.
They are not derived from an individual inbound WeChat participant.

Consequently, this release must not be represented as production-ready for
multi-participant role attribution. If AIVAN Core runs with `AIVAN_ENV=production`,
the service identity variables are required and every event is attributed to that
single configured identity. Per-channel and per-participant trusted identity
binding is a Stage 4 delivery requirement. Core RBAC and the human approval gate
remain authoritative; Stage 3 does not bypass either control.
