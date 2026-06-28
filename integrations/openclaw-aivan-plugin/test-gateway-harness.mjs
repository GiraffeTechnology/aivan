/**
 * Gateway integration test for openclaw-aivan plugin.
 *
 * Simulates exactly what OpenClaw Gateway 2026.6.9 does:
 *   1. load the plugin and call register(api)
 *   2. api.registerAgentHarness() stores the harness
 *   3. harness.supports(ctx) is called for each session
 *   4. harness.runAttempt(params) is called with the prompt
 *
 * A lightweight HTTP server stands in for the AIVAN backend on port 8765.
 * Run with: node test-gateway-harness.mjs
 */

import { createServer } from "http";
import { pathToFileURL } from "url";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// ── 1. Mock AIVAN server on port 8765 ─────────────────────────────────────────
let mockServerMode = "success"; // "success" | "error"
let lastReceivedEvent = null;

const MOCK_PORT = 8765;
const mockServer = createServer((req, res) => {
  let body = "";
  req.on("data", (d) => (body += d));
  req.on("end", () => {
    if (req.url === "/api/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok", version: "mock-1.0.0" }));
      return;
    }

    if (req.url === "/invoke" && req.method === "POST") {
      try {
        lastReceivedEvent = JSON.parse(body);
      } catch {
        lastReceivedEvent = null;
      }
      if (mockServerMode === "error") {
        // AIVAN's global handler still returns structured JSON on failure.
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({ status: "error", output: "Internal error: RuntimeError", artifacts: [] })
        );
        return;
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          status: "ok",
          output:
            "感谢您的询价！我们将为您寻找白色纯棉衬衣的供应商，45天内交货至温哥华。请稍候。",
          artifacts: [],
          trace_id: "mock-trace-001",
          project_id: "proj-mock-001",
        })
      );
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
  });
});

await new Promise((resolve) => mockServer.listen(MOCK_PORT, "127.0.0.1", resolve));

// ── 2. Load the plugin ────────────────────────────────────────────────────────
const pluginPath = path.join(__dirname, "dist", "index.js");
const pluginUrl = pathToFileURL(pluginPath).href;
const plugin = await import(pluginUrl);

// ── 3. Simulate Gateway registerAgentHarness ──────────────────────────────────
let registeredHarness = null;

const mockApi = {
  registerAgentHarness(harness) {
    registeredHarness = harness;
  },
};

plugin.register(mockApi);

// ── Helpers ───────────────────────────────────────────────────────────────────
let passed = 0;
let failed = 0;

function assert(label, condition, detail = "") {
  if (condition) {
    console.log(`  PASS  ${label}`);
    passed++;
  } else {
    console.error(`  FAIL  ${label}${detail ? " — " + detail : ""}`);
    failed++;
  }
}

function assertShape(label, obj, requiredKeys) {
  const missing = requiredKeys.filter((k) => !(k in obj));
  assert(
    label,
    missing.length === 0,
    missing.length ? `missing keys: ${missing.join(", ")}` : ""
  );
}

// ── Test 1: register() ────────────────────────────────────────────────────────
console.log("\n── Test 1: plugin registration");
assert("register() sets harness", registeredHarness !== null);
assert("harness has id", typeof registeredHarness?.id === "string");
assert("harness has label", typeof registeredHarness?.label === "string");
assert("harness has supports()", typeof registeredHarness?.supports === "function");
assert("harness has runAttempt()", typeof registeredHarness?.runAttempt === "function");

// ── Test 2: supports() shape ──────────────────────────────────────────────────
console.log("\n── Test 2: supports() return shape (AgentHarnessSupport)");
const supportResult = registeredHarness.supports({ sessionId: "sess-001" });
assert("supports() returns object", typeof supportResult === "object" && supportResult !== null);
assert("supports.supported is boolean", typeof supportResult?.supported === "boolean");
assert("supports.supported is true", supportResult?.supported === true);

// ── Test 3: runAttempt() success path ─────────────────────────────────────────
console.log("\n── Test 3: runAttempt() — AIVAN online, WeChat prompt");
mockServerMode = "success";
lastReceivedEvent = null;

const TEST_PARAMS = {
  prompt: "帮我询价 10000 件白色纯棉衬衣，45 天内交货温哥华",
  sessionId: "sess-wechat-001",
  senderId: "weixin-user-abc",
  channel: "weixin",
};

const successResult = await registeredHarness.runAttempt(TEST_PARAMS);

assertShape("result has all EmbeddedRunAttemptResult keys", successResult, [
  "aborted",
  "externalAbort",
  "timedOut",
  "idleTimedOut",
  "timedOutDuringCompaction",
  "promptError",
  "promptErrorSource",
  "sessionIdUsed",
  "messagesSnapshot",
  "assistantTexts",
  "toolMetas",
  "lastAssistant",
  "didSendViaMessagingTool",
  "messagingToolSentTexts",
  "messagingToolSentMediaUrls",
  "messagingToolSentTargets",
  "cloudCodeAssistFormatError",
]);
assert("aborted is false", successResult.aborted === false);
assert("timedOut is false", successResult.timedOut === false);
assert("assistantTexts is non-empty array", Array.isArray(successResult.assistantTexts) && successResult.assistantTexts.length > 0);
assert("assistantTexts[0] has content", successResult.assistantTexts[0]?.length > 0);
assert("messagesSnapshot is array", Array.isArray(successResult.messagesSnapshot));
assert("lastAssistant.role = assistant", successResult.lastAssistant?.role === "assistant");
assert("lastAssistant.content is array", Array.isArray(successResult.lastAssistant?.content));
assert("lastAssistant.content[0].type = text", successResult.lastAssistant?.content?.[0]?.type === "text");
assert("lastAssistant has api", typeof successResult.lastAssistant?.api === "string");
assert("lastAssistant has model", typeof successResult.lastAssistant?.model === "string");
assert("lastAssistant has usage", typeof successResult.lastAssistant?.usage === "object");
assert("lastAssistant.usage has cost", typeof successResult.lastAssistant?.usage?.cost === "object");
assert("lastAssistant has stopReason", typeof successResult.lastAssistant?.stopReason === "string");
assert("lastAssistant has timestamp", typeof successResult.lastAssistant?.timestamp === "number");
assert("sessionIdUsed matches", successResult.sessionIdUsed === TEST_PARAMS.sessionId);
assert("invoke called on AIVAN", lastReceivedEvent !== null);
assert("payload.user_input = prompt", lastReceivedEvent?.user_input === TEST_PARAMS.prompt);
assert("payload.context.channel = weixin", lastReceivedEvent?.context?.channel === "weixin");
assert("payload.session_id = sessionId", lastReceivedEvent?.session_id === TEST_PARAMS.sessionId);
assert("payload.context.sender_id = senderId", lastReceivedEvent?.context?.sender_id === TEST_PARAMS.senderId);

console.log("  reply:", successResult.assistantTexts[0]);

// ── Test 4: runAttempt() — AIVAN error ────────────────────────────────────────
console.log("\n── Test 4: runAttempt() — AIVAN returns 500 (visible diagnostic, no throw)");
mockServerMode = "error";

const errorResult = await registeredHarness.runAttempt(TEST_PARAMS);
assert("returns object (no throw)", typeof errorResult === "object" && errorResult !== null);
assertShape("error result has required keys", errorResult, ["aborted", "messagesSnapshot", "assistantTexts", "lastAssistant"]);
// P0-3: bridge must NOT swallow the error into an empty pass-through; it surfaces
// AIVAN's structured output as a visible diagnostic so WeChat shows something.
assert("assistantTexts is non-empty (visible diagnostic)", Array.isArray(errorResult.assistantTexts) && errorResult.assistantTexts.length > 0);
assert("diagnostic mentions internal error", /Internal error|出错/.test(errorResult.assistantTexts[0] ?? ""));

// ── Test 5: empty prompt ──────────────────────────────────────────────────────
console.log("\n── Test 5: runAttempt() — empty prompt (no crash)");
mockServerMode = "success";

const emptyResult = await registeredHarness.runAttempt({ sessionId: "sess-002" });
assert("returns object (no throw)", typeof emptyResult === "object");
assert("assistantTexts is empty", Array.isArray(emptyResult.assistantTexts) && emptyResult.assistantTexts.length === 0);

// ── Test 6: health() ──────────────────────────────────────────────────────────
console.log("\n── Test 6: health() direct call");
const healthResult = await plugin.health();
assert("health.healthy is true", healthResult.healthy === true);
assert("health.version is string", typeof healthResult.version === "string");

// ── Summary ───────────────────────────────────────────────────────────────────
mockServer.close();

console.log(`\n${"=".repeat(60)}`);
if (failed === 0) {
  console.log(`GATEWAY INTEGRATION TEST: PASS (${passed} checks)`);
} else {
  console.log(`GATEWAY INTEGRATION TEST: FAIL (${failed} failed, ${passed} passed)`);
}
console.log("=".repeat(60));

process.exit(failed > 0 ? 1 : 0);
