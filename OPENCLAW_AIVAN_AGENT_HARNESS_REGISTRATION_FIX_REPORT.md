# OpenClaw AIVAN Agent Harness Registration Fix Report

Date: 2026-06-29

## 1. Root Cause

OpenClaw loaded `openclaw-aivan`, but did not invoke its named `register(api)` export. The installed runtime only registers agent harnesses through the default plugin entry contract: a default function, or a default object with `register` / `activate`.

The previous plugin used `defineToolPlugin({...})` as the default export and kept `register(api)` as a separate named export, so runtime inspection showed:

```text
agentHarnessIds: []
shape: non-capability
```

That is why mobile WeChat inbound reached the current Gateway, but OpenClaw never called `openclaw-aivan`, `runAttempt`, or AIVAN.

## 2. OpenClaw Contract Discovered

Local SDK docs and runtime inspection showed the required contract:

```ts
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

export default definePluginEntry({
  id: "openclaw-aivan",
  register(api) {
    api.registerAgentHarness(harness);
  },
});
```

The OpenClaw runtime resolves the module default export and calls `definition.register ?? definition.activate`, or calls the default export directly if it is a function.

## 3. Why The Plugin Loaded But Had Empty Harness IDs

The plugin metadata and config schema loaded from the default `defineToolPlugin` export, but the harness was registered only in a named `register` export. OpenClaw did not call that named export, so `api.registerAgentHarness()` never ran.

## 4. Files Changed

```text
integrations/openclaw-aivan-plugin/index.ts
integrations/openclaw-aivan-plugin/dist/index.js
integrations/openclaw-aivan-plugin/dist/index.d.ts
integrations/openclaw-aivan-plugin/test-gateway-harness.mjs
```

Changes:

```text
- switched default export to definePluginEntry({ register })
- preserved register(api) and existing AIVAN HTTP forwarding logic
- added output fallback when reply_text is absent
- added AIVAN HTTP status/body-field logging
- updated the harness test to load the built default entry exactly as OpenClaw does
```

## 5. Tests Added

`test-gateway-harness.mjs` now verifies:

```text
- built plugin default entry has a callable register contract
- fake api.registerAgentHarness() is called exactly once
- registered harness id is openclaw-aivan
- runAttempt() handles a WeChat-like RFQ prompt
- mocked AIVAN reply_text/output becomes non-empty assistantTexts
- lastAssistant exists
- terminal pass-through is not used on success
```

## 6. Build Command Output

Commands:

```bash
cd /opt/giraffe/aivan/integrations/openclaw-aivan-plugin
npm install
npm run build
npx tsc
node test-gateway-harness.mjs
```

Key output:

```text
npm install: added 310 packages, audited 311 packages, found 0 vulnerabilities
npm run build: tsc completed
npx tsc: completed
GATEWAY INTEGRATION TEST: PASS (34 checks)
```

Harness success included:

```text
[aivan] registerAgentHarness registered successfully
[aivan] forwarding event: prompt_len=22 session=sess-wechat-001
[aivan] AIVAN HTTP status=200 fields={"status":"ok","output":"已收到您的询价需求：5000件格子衬衫，45天交东京。","reply_text":"已收到您的询价需求：5000件格子衬衫，45天交东京。"}
[aivan] AIVAN reply: 已收到您的询价需求：5000件格子衬衫，45天交东京。
```

## 7. OpenClaw Inspect Before / After

Before reinstall:

```json
"agentHarnessIds": []
```

After reinstall:

```json
"agentHarnessIds": ["openclaw-aivan"],
"shape": "plain-capability",
"capabilities": [
  {
    "kind": "agent-harness",
    "ids": ["openclaw-aivan"]
  }
]
```

Installed source:

```text
/root/.openclaw/extensions/openclaw-aivan/dist/index.js
sourcePath: /opt/giraffe/aivan/integrations/openclaw-aivan-plugin
```

## 8. Gateway Restart Evidence

The first restart failed because `/tmp` was full:

```text
Gateway failed to start: failed to acquire gateway lock ... ENOSPC
```

Cause:

```text
/tmp/openclaw-trace-watch-AIVAN-TRACE-20260629-200505-HKT.log: 3.6G
```

Fix:

```text
removed the generated trace-watch temp log
/tmp changed from 100% used to 6% used
```

Gateway then restarted successfully:

```text
Active: active (running)
Main PID: 445212
[aivan] registerAgentHarness registered successfully
[gateway] http server listening (3 plugins: memory-core, openclaw-aivan, openclaw-weixin)
[gateway] ready
```

## 9. Final WeChat Result

Phase 6 runtime acceptance passed before the WeChat retest:

```text
agentHarnessIds non-empty: yes
registerAgentHarness ran: yes
runAttempt harness test passed: yes
plugin reached live AIVAN: yes
AIVAN HTTP status: 200
AIVAN reply_text/output non-empty: yes
assistantTexts non-empty: yes
```

Live harness smoke against AIVAN returned:

```json
{
  "harnessId": "openclaw-aivan",
  "assistantTexts": [
    "AIVAN 处理请求时遇到后端依赖错误，请稍后再试。"
  ],
  "lastAssistantText": "AIVAN 处理请求时遇到后端依赖错误，请稍后再试。",
  "sessionIdUsed": "harness-smoke-20260629"
}
```

The required mobile WeChat trace was requested:

```text
AIVAN-TRACE-HARNESS-FIX 询价5000件格子衬衫，45天交东京，高品质
```

Result:

```text
inbound trace observed: no
log file where it appeared: none
WeChat final reply captured: no
REAL WECHAT ACCEPTANCE: not marked PASS
```

No `AIVAN-TRACE-HARNESS-FIX` line appeared in a 180-second live tail or the focused persisted-log grep.

## 10. PR Required

Yes. This is a code fix, not only a live configuration change.

Draft PR opened:

```text
https://github.com/GiraffeTechnology/aivan/pull/18
branch: codex/openclaw-aivan-agent-harness-registration
commit: 182b046370059a8043ac267de814d40c3720c903
```

CODE FIX REQUIRED — new PR opened
