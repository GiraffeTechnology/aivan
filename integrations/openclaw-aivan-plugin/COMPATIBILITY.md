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

## Identity boundary and verification limits

The static service identity comes from `AIVAN_TENANT_ID`, `AIVAN_ACTOR_ID`,
`AIVAN_ROLE_CONTEXT`, `AIVAN_CONVERSATION_ROLE` and `AIVAN_EXECUTION_MODE`.
`AIVAN_CHANNEL_ACCOUNT_ID` binds the trusted channel account. Current source also
hashes channel/account/sender into a separate participant ID and supplies
participant role/conversation headers. Core requires those participant assertions
in production and keeps them separate from the authenticated service actor.

The earlier Stage 3 single-identity description is historical; the current
Stage 4 code includes participant binding. That binding still depends on trusted
upstream gateway metadata. Synthetic harness tests do not prove real-provider
sender authentication, account connectivity or multi-account deployment behavior.

The `wechat` legacy callback and guided-relay path are not evidence of a live
personal-WeChat or WeCom integration. There is no WeCom-specific connector in
this bridge. The gateway owns platform access, and any configured integration
must follow the platform's restrictions. All outbound actions require human
approval; the first MyAivan web iteration uses manual review/copy/send for IM.
