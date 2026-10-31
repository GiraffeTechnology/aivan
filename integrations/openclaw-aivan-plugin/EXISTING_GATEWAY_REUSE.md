# Existing Gateway reuse: local compatibility candidate

This candidate fixes explicit AgentHarness selection and the Core alias for
Tencent's `openclaw-weixin` channel. It is not a deployed release or a live
WeChat acceptance result. It does not install a Gateway, Tencent's channel
plugin, account credentials, Node.js or a model provider.

## Preserve the working channel

Historical Aivan commit `37ec1d5d893ac4358e5499e0546e2ba177d46457` records a real
WeChat round trip with bridge 0.1.0 and Gateway 2026.6.10. That round trip returned
a backend dependency error, so it does not prove completed RFQ processing.
The earlier registration fix is PR 18; bridge 0.1.0 was used both before and
after that fix. An enabled plugin or version string alone is insufficient:
runtime inspection must show the `openclaw-aivan` AgentHarness.

PR 59 intentionally stopped automatic personal-IM replies. This candidate
preserves that rule: matched trade requests create/retrieve Aivan state, but
return no `assistantTexts`. It must not be replaced by the old automatic-reply
implementation. Core approval and delivery state remain authoritative.

Before changing an existing Gateway, record its exact binary version, plugin
versions and resolved entrypoints without exporting credentials. Preserve its
existing account state and rollback copy. Do not replace Tencent's plugin or
repeat QR login merely to install this bridge. A previously observed Tencent
2.4.4 installation has not been tested with this candidate; the current upstream
documentation/package versions are not a reason to upgrade it automatically.

## Explicit selection on the tested SDK

The locally available SDK is OpenClaw `2026.7.2-beta.7`. Its support context
contains provider/model/runtime facts, not the incoming message. The bridge now
advertises `autoSelection.providerIds: []` and accepts only an explicitly
requested `openclaw-aivan` runtime. It never claims arbitrary providers or another
agent's runtime. The existing per-attempt trade-intent boundary still applies.
An explicitly selected non-trade turn returns an empty result and makes no Core
call. The SDK does not replay that turn through a different runtime. Do not
describe this as agent fallback or pass-through. A dedicated trading UI should
explain this scope outside the automatic-reply path.

The inspected SDK has a pre-selection `before_model_resolve` hook with prompt
input and provider/model override results. It has no direct intent-to-harness
result in that contract. Using it would require an independently reviewed,
configured provider/model route and raw-conversation hook access; this candidate
does not add such a hook, broaden plugin access or invent a model route. Channel
bindings themselves select by channel/account/peer, not message intent.

The tested SDK uses per-model `agentRuntime.id` and channel bindings. For example,
merge the following *shape* into the existing configuration after selecting a
dedicated agent, an already configured model and an already admitted account/peer:

```json
{
  "agents": {
    "entries": {
      "main": {"default": true, "model": "existing-provider/existing-model"},
      "aivan": {
        "model": "existing-provider/existing-model",
        "models": {
          "existing-provider/existing-model": {"agentRuntime": {"id": "openclaw-aivan"}}
        }
      }
    }
  },
  "bindings": [{
    "agentId": "aivan",
    "match": {
      "channel": "openclaw-weixin",
      "accountId": "EXISTING_ACCOUNT_ID",
      "peer": {"kind": "direct", "id": "EXISTING_ALLOWED_PEER_ID"}
    }
  }]
}
```

This is a schema-validated example, not an operational preset. Preserve other
agents, the existing default agent and unrelated bindings. Do not change the
global model/runtime to route every conversation to Aivan. Whole-agent
`agents.entries.<id>.agentRuntime` is rejected by the tested SDK schema. Older
2026.6.x Gateway configuration compatibility remains unverified: inspect that
installed version's supported model/runtime contract before applying any example.
Do not invent model credentials or bypass provider preparation checks.

The Gateway service supplies `AIVAN_BASE_URL` for the existing Core endpoint and
the existing authorized `AIVAN_API_KEY`, `AIVAN_TENANT_ID`, `AIVAN_ACTOR_ID`,
`AIVAN_ROLE_CONTEXT` and `AIVAN_CHANNEL_ACCOUNT_ID` bindings. Credentials belong in
the authorized service configuration, never in this archive or a shared report.
The upstream channel remains responsible for trustworthy account/sender metadata.

## Package and controlled installation plan

The npm-pack tarball contains the compiled bridge and its manifest/contracts.
Its internal version remains 0.3.0; identify this unpublished candidate by the
supplied archive SHA-256 and patch, not by that version alone. It requires the
compatible existing Gateway/Node runtime and declared `typebox` dependency. It
is not a standalone offline Gateway distribution.

On the tested CLI, an authorized operator can install an npm-pack artifact with
`openclaw plugins install npm-pack:<reviewed-archive.tgz>`. Check the older
installed CLI's archive syntax first. Do not execute an update or restart until
the existing target configuration and rollback plan have been reviewed. No such
installation or restart was performed for this candidate.

After installation, inspect the resolved plugin entrypoint and registered harness,
verify only the intended account/peer routes to the dedicated agent, and preserve
the existing Tencent account/login state. The Core alias change must be applied
alongside the bridge; the npm archive does not contain or upgrade Aivan Core.

## Required integrated verification

Use synthetic business content through the existing official WeChat channel:
inbound message -> authenticated tenant/account/participant -> durable business
state and pending draft -> explicit human review -> permitted outbound action ->
delivery receipt and replay/restart recovery. Capture actual versions and
non-secret evidence for that run. Aivan's current WeChat capability remains
guided relay; adding a direct approved Tencent transport is not implemented here.

The Core rejects unapproved/stale draft sending, preserves approval fingerprints,
and commits uncertain-delivery state before external I/O. These controls do not
automatically constrain another Gateway agent or tool. Tencent's optional send
hook is not a substitute for Aivan's durable approval gate. Neither synthetic
Gateway tests nor schema validation establish real account connectivity or a
complete live approval-to-delivery chain.
