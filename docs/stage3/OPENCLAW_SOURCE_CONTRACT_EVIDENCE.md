# OpenClaw source contract evidence

Verified on 2026-08-03 against `GiraffeTechnology/openclaw/main` after it was
synchronized to upstream `openclaw/openclaw/main`.

- Current commit: `1e06fd443033b8aa2fd638ee66b7fdad1168b8aa`
- Current source version: `2026.7.2`
- Previous Giraffe fork head retained at:
  `archive/pre-upstream-sync-20260803`
- Latest npm SDK available during verification: `2026.6.8`

The current fork source still defines:

- `definePluginEntry({ ..., register })` in `src/plugin-sdk/plugin-entry.ts`
- `OpenClawPluginApi.registerTool(tool, opts?)` in
  `src/plugins/plugin-api.types.ts`
- `OpenClawPluginApi.registerAgentHarness(harness)` in the same API contract

The AIVAN package compiles against the latest published SDK and its manifest and
runtime registration are inspected with the OpenClaw CLI. The peer range admits
both `2026.6.x` and `2026.7.x`; the source commit above is the authoritative
compatibility baseline until `2026.7.2` is published to npm.
