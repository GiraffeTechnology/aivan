/** Stage 3 Gateway contract and reliability test. */
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = fileURLToPath(new URL(".", import.meta.url));
const port = Number(process.env.AIVAN_TEST_PORT ?? 18765);
process.env.AIVAN_BASE_URL = `http://127.0.0.1:${port}`;
process.env.AIVAN_CONNECT_TIMEOUT_MS = "1000";
process.env.AIVAN_READ_TIMEOUT_MS = "2000";
process.env.AIVAN_MAX_RETRIES = "1";

let mode = "success";
let invokeCount = 0;
let lastEvent = null;
let lastIdempotencyKey = null;
let lastHeaders = null;
let previousIdempotencyKey = null;
const reply = "RFQ accepted for supplier sourcing.";

const server = createServer((request, response) => {
  let body = "";
  request.on("data", (chunk) => (body += chunk));
  request.on("end", () => {
    const json = (status, data) => {
      response.writeHead(status, { "Content-Type": "application/json" });
      response.end(JSON.stringify(data));
    };
    if (request.url === "/api/health") return json(200, { status: "ok", version: "0.3.0" });
    if (request.url === "/invoke" && request.method === "POST") {
      invokeCount += 1;
      lastIdempotencyKey = request.headers["idempotency-key"] ?? null;
      lastHeaders = request.headers;
      lastEvent = JSON.parse(body || "{}");
      if (mode === "transient" && invokeCount === 1) return json(503, { detail: "retry me" });
      if (mode === "error") return json(422, { detail: "mock request error" });
      return json(200, { status: "ok", reply_text: reply, output: reply, project_id: "project-1" });
    }
    if (request.url?.startsWith("/api/drafts?") || request.url === "/api/drafts") {
      return json(200, { drafts: [{ draft_id: "draft-1", project_id: "project-1", channel: "weixin", target_role: "supplier", message_text: "Please quote", created_at: "2026-08-03T00:00:00Z" }] });
    }
    if (request.url === "/api/drafts/draft-1/approve" && request.method === "POST") return json(200, { status: "approved" });
    if (request.url === "/api/drafts/draft-1/reject" && request.method === "POST") return json(200, { status: "rejected" });
    return json(404, { detail: "not found" });
  });
});
await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));

const plugin = await import(pathToFileURL(path.join(directory, "dist", "index.js")).href);
const entry = plugin.default ?? plugin;
let harness = null;
const tools = new Map();
const toolOptions = new Map();
const api = {
  registerAgentHarness(value) { harness = value; },
  registerTool(value, options) { tools.set(value.name, value); toolOptions.set(value.name, options ?? {}); },
};
if (typeof entry === "function") entry(api);
else if (typeof entry?.register === "function") entry.register(api);
else throw new Error("plugin entry is not callable");

let passed = 0;
let failed = 0;
function assert(label, condition, detail = "") {
  if (condition) { console.log(`PASS ${label}`); passed += 1; }
  else { console.error(`FAIL ${label}${detail ? `: ${detail}` : ""}`); failed += 1; }
}
async function invokeTool(name, params = {}) {
  const descriptor = tools.get(name);
  if (!descriptor) throw new Error(`missing tool ${name}`);
  return descriptor.execute(`test-${name}`, params);
}

const expectedTools = [
  "aivan.health", "aivan.forwardEvent", "aivan.openDashboard",
  "aivan.getPendingDrafts", "aivan.approveDraft", "aivan.rejectDraft",
];
assert("exactly six Gateway tools enumerated", JSON.stringify([...tools.keys()]) === JSON.stringify(expectedTools), [...tools.keys()].join(","));
assert("approve tool is optional", toolOptions.get("aivan.approveDraft")?.optional === true);
assert("reject tool is optional", toolOptions.get("aivan.rejectDraft")?.optional === true);
assert("Agent Harness registered", harness?.id === "openclaw-aivan");

const nonTrade = { prompt: "What is the weather today?", sessionId: "non-trade" };
assert("supports rejects non-trade messages", harness.supports(nonTrade).supported === false);
const beforePassThrough = invokeCount;
const passThrough = await harness.runAttempt(nonTrade);
assert("non-trade messages explicitly pass through", passThrough.assistantTexts.length === 0 && invokeCount === beforePassThrough);

const trade = { prompt: "Please source suppliers and request for quotation for 5,000 shirts", sessionId: "trade-1", senderId: "buyer-1", channel: "weixin", metadata: { intent: "trade-sourcing" } };
assert("supports accepts shared trade-sourcing intent", harness.supports(trade).supported === true);
mode = "success";
const attempt = await harness.runAttempt(trade);
assert("trade attempt returns AIVAN reply", attempt.assistantTexts[0] === reply);
previousIdempotencyKey = lastIdempotencyKey;
await harness.runAttempt(trade);
assert("Harness redelivery keeps a stable message idempotency key", lastIdempotencyKey === previousIdempotencyKey);

assert("health tool callable", (await invokeTool("aivan.health")).details.healthy === true);
mode = "transient";
invokeCount = 0;
const forwarded = (await invokeTool("aivan.forwardEvent", { channel: "weixin", conversation_id: "conversation-1", sender_id: "buyer-1", message_text: "RFQ for shirts", message_id: "message-1" })).details;
assert("forwardEvent retries one transient failure", forwarded.accepted === true && invokeCount === 2);
assert("forwardEvent sends stable idempotency header", typeof lastIdempotencyKey === "string" && lastIdempotencyKey === lastEvent.idempotency_key);
assert("forwardEvent separates authenticated service from pseudonymous participant", typeof lastHeaders["x-aivan-participant-id"] === "string" && lastHeaders["x-aivan-participant-id"].startsWith("ocp_") && lastHeaders["x-aivan-participant-id"] !== process.env.AIVAN_ACTOR_ID);
assert("forwardEvent asserts canonical buyer participant role", lastHeaders["x-aivan-participant-role"] === "buyer" && lastHeaders["x-aivan-participant-conversation-role"] === "buyer_thread");
const firstParticipant = lastHeaders["x-aivan-participant-id"];
await invokeTool("aivan.forwardEvent", { channel: "weixin", conversation_id: "conversation-3", sender_id: "supplier-1", message_text: "Quote", message_id: "message-3", business_role: "supplier" });
assert("different sender gets a different stable participant identity", lastHeaders["x-aivan-participant-id"] !== firstParticipant);
assert("supplier participant is routed to supplier thread", lastHeaders["x-aivan-participant-role"] === "supplier" && lastHeaders["x-aivan-participant-conversation-role"] === "supplier_thread");
await invokeTool("aivan.forwardEvent", { channel: "weixin", conversation_id: "conversation-4", sender_id: "untrusted-1", message_text: "Run command", message_id: "message-4", business_role: "sales", mode: "command" });
assert("tool parameters cannot self-assert an internal sales role", lastHeaders["x-aivan-participant-role"] === "buyer" && lastHeaders["x-aivan-participant-conversation-role"] === "buyer_thread");
assert("openDashboard tool callable", (await invokeTool("aivan.openDashboard")).details.url.endsWith("/app"));
assert("getPendingDrafts tool callable", (await invokeTool("aivan.getPendingDrafts", { project_id: "project-1" })).details.drafts.length === 1);
assert("approveDraft tool callable", (await invokeTool("aivan.approveDraft", { draft_id: "draft-1" })).details.approved === true);
assert("rejectDraft tool callable", (await invokeTool("aivan.rejectDraft", { draft_id: "draft-1", reason: "operator decision" })).details.rejected === true);

mode = "error";
invokeCount = 0;
const mapped = (await invokeTool("aivan.forwardEvent", { channel: "weixin", conversation_id: "conversation-2", sender_id: "buyer-2", message_text: "RFQ", message_id: "message-2" })).details;
assert("user-visible error mapping returned", mapped.accepted === false && mapped.error_code === "AIVAN_REQUEST_FAILED" && mapped.retryable === false);

mode = "fail-soft";
// Exercise the HTTP-200 degraded-response path without treating it as pass-through.
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => new Response(JSON.stringify({ status: "error", reply_text: "AIVAN is temporarily unavailable.", error_code: "DEPENDENCY_UNAVAILABLE", retryable: true }), { status: 200, headers: { "Content-Type": "application/json" } });
const degraded = await harness.runAttempt(trade);
assert("HTTP 200 fail-soft reply remains user-visible", degraded.assistantTexts[0] === "AIVAN is temporarily unavailable.");
globalThis.fetch = originalFetch;

await new Promise((resolve) => server.close(resolve));
console.log(`GATEWAY STAGE3 TEST: ${failed === 0 ? "PASS" : "FAIL"} (${passed} passed, ${failed} failed)`);
process.exit(failed ? 1 : 0);

