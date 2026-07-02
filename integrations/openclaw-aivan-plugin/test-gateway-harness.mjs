/**
 * Gateway integration test for openclaw-aivan plugin.
 *
 * Loads the built plugin entry the way OpenClaw does, registers an
 * AgentHarness through a fake runtime API, then exercises runAttempt().
 *
 * Run with: node test-gateway-harness.mjs
 */

import { createServer } from "http";
import { pathToFileURL } from "url";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const MOCK_PORT = Number(process.env.AIVAN_TEST_PORT ?? 18765);
process.env.AIVAN_BASE_URL = `http://127.0.0.1:${MOCK_PORT}`;

// -- Mock AIVAN server --------------------------------------------------------
let mockServerMode = "success"; // "success" | "error"
let lastReceivedEvent = null;

const mockReply =
  "已收到您的询价需求：5000件格子衬衫，45天交东京。";

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
        res.writeHead(422, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ detail: "mock error: project not found" }));
        return;
      }

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          status: "ok",
          reply_text: mockReply,
          output: mockReply,
        })
      );
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
  });
});

await new Promise((resolve) =>
  mockServer.listen(MOCK_PORT, "127.0.0.1", resolve)
);

// -- Load the plugin entry exactly as OpenClaw does ---------------------------
const pluginPath = path.join(__dirname, "dist", "index.js");
const pluginUrl = pathToFileURL(pluginPath).href;
const plugin = await import(pluginUrl);
const pluginEntry = plugin.default ?? plugin;

let registeredHarness = null;
let registerCalls = 0;

const mockApi = {
  registerAgentHarness(harness) {
    registerCalls += 1;
    registeredHarness = harness;
  },
};

if (typeof pluginEntry === "function") {
  pluginEntry(mockApi);
} else if (typeof pluginEntry?.register === "function") {
  pluginEntry.register(mockApi);
} else {
  throw new Error("built plugin entry has no callable register contract");
}

// -- Helpers -----------------------------------------------------------------
let passed = 0;
let failed = 0;

function assert(label, condition, detail = "") {
  if (condition) {
    console.log(`  PASS  ${label}`);
    passed++;
  } else {
    console.error(`  FAIL  ${label}${detail ? " - " + detail : ""}`);
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

// -- Test 1: registration -----------------------------------------------------
console.log("\n-- Test 1: OpenClaw plugin-entry registration");
assert("registerAgentHarness called exactly once", registerCalls === 1);
assert("register() sets harness", registeredHarness !== null);
assert("harness id is openclaw-aivan", registeredHarness?.id === "openclaw-aivan");
assert("harness has label", typeof registeredHarness?.label === "string");
assert("harness has supports()", typeof registeredHarness?.supports === "function");
assert("harness has runAttempt()", typeof registeredHarness?.runAttempt === "function");

// -- Test 2: supports() shape -------------------------------------------------
console.log("\n-- Test 2: supports() return shape");
const supportResult = registeredHarness.supports({ sessionId: "sess-001" });
assert("supports() returns object", typeof supportResult === "object" && supportResult !== null);
assert("supports.supported is boolean", typeof supportResult?.supported === "boolean");
assert("supports.supported is true", supportResult?.supported === true);

// -- Test 3: runAttempt success path -----------------------------------------
console.log("\n-- Test 3: runAttempt() success path");
mockServerMode = "success";
lastReceivedEvent = null;

const TEST_PARAMS = {
  prompt: "询价5000件格子衬衫，45天交东京，高品质",
  sessionId: "sess-wechat-001",
  senderId: "weixin-user-abc",
  channel: "weixin",
};

const successResult = await registeredHarness.runAttempt(TEST_PARAMS);

assertShape("result has EmbeddedRunAttemptResult keys", successResult, [
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
assert("assistantTexts[0] uses AIVAN reply", successResult.assistantTexts[0] === mockReply);
assert("lastAssistant exists", successResult.lastAssistant != null);
assert("lastAssistant.role = assistant", successResult.lastAssistant?.role === "assistant");
assert("lastAssistant.content[0].type = text", successResult.lastAssistant?.content?.[0]?.type === "text");
assert("lastAssistant.content[0].text uses AIVAN reply", successResult.lastAssistant?.content?.[0]?.text === mockReply);
assert("terminal pass-through is not used", successResult.lastAssistant !== undefined && successResult.assistantTexts.length > 0);
assert("sessionIdUsed matches", successResult.sessionIdUsed === TEST_PARAMS.sessionId);
assert("event forwarded to AIVAN", lastReceivedEvent !== null);
assert("event.message_text = prompt", lastReceivedEvent?.message_text === TEST_PARAMS.prompt);
assert("event.channel = weixin", lastReceivedEvent?.channel === "weixin");
assert("event.conversation_id = sessionId", lastReceivedEvent?.conversation_id === TEST_PARAMS.sessionId);
assert("event.sender_id = senderId", lastReceivedEvent?.sender_id === TEST_PARAMS.senderId);
assert("event.source = openclaw", lastReceivedEvent?.source === "openclaw");
assert("event.mode = auto", lastReceivedEvent?.mode === "auto");

console.log("  reply:", successResult.assistantTexts[0]);

// -- Test 4: AIVAN error path -------------------------------------------------
console.log("\n-- Test 4: runAttempt() AIVAN error path");
mockServerMode = "error";

const errorResult = await registeredHarness.runAttempt(TEST_PARAMS);
assert("returns object (no throw)", typeof errorResult === "object" && errorResult !== null);
assertShape("error result has required keys", errorResult, ["aborted", "messagesSnapshot", "assistantTexts", "lastAssistant"]);
assert("assistantTexts is empty on AIVAN error", Array.isArray(errorResult.assistantTexts) && errorResult.assistantTexts.length === 0);

// -- Test 5: empty prompt -----------------------------------------------------
console.log("\n-- Test 5: runAttempt() empty prompt");
mockServerMode = "success";

const emptyResult = await registeredHarness.runAttempt({ sessionId: "sess-002" });
assert("returns object (no throw)", typeof emptyResult === "object");
assert("assistantTexts is empty", Array.isArray(emptyResult.assistantTexts) && emptyResult.assistantTexts.length === 0);

// -- Test 6: health() ---------------------------------------------------------
console.log("\n-- Test 6: health() direct call");
const healthResult = await plugin.health();
assert("health.healthy is true", healthResult.healthy === true);
assert("health.version is string", typeof healthResult.version === "string");

// -- Summary -----------------------------------------------------------------
mockServer.close();

console.log(`\n${"=".repeat(60)}`);
if (failed === 0) {
  console.log(`GATEWAY INTEGRATION TEST: PASS (${passed} checks)`);
} else {
  console.log(`GATEWAY INTEGRATION TEST: FAIL (${failed} failed, ${passed} passed)`);
}
console.log("=".repeat(60));

process.exit(failed > 0 ? 1 : 0);
