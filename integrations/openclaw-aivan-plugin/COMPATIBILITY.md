# AIVAN OpenClaw compatibility matrix

| Artifact | Supported version | Verification basis |
|---|---:|---|
| AIVAN Core | 0.3.x | `/api/health` and Stage 3 contract tests |
| AIVAN OpenClaw plugin | 0.3.x | package, manifest, build and Gateway harness |
| AIVAN trade-salesperson SKILL | 0.3.x | shared `intent-boundary.json` contract |
| OpenClaw Gateway | 2026.7.2-beta.7 or stable 2026.7.x | published SDK build plus synchronized fork source contract |
| Node.js | >=22.22.3 <23, >=24.15.0 <25, or >=25.9.0 | OpenClaw SDK engine requirement |

The current OpenClaw source baseline is `GiraffeTechnology/openclaw` commit
`1e06fd443033b8aa2fd638ee66b7fdad1168b8aa` (package version `2026.7.2`),
synchronized from `openclaw/openclaw/main` on 2026-08-03. The reproducible
package build uses the security-fixed prerelease SDK package `2026.7.2-beta.7`
and separately verifies the current `2026.7.2` fork source contract. A stable
2026.7.2 package must replace the prerelease as soon as it is published and
passes the same build, audit and Gateway harness gates.
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
