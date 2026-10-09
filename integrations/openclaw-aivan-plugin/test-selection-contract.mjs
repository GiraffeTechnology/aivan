/** Regression coverage for the public OpenClaw AgentHarness selection contract. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { register } from "./dist/index.js";

let harness;
register({
  registerTool() {},
  registerAgentHarness(value) { harness = value; },
});

// AgentHarnessSupportContext supplies runtime/provider/model facts, not a prompt.
const supportContext = {
  provider: "test-provider",
  modelId: "test-model",
  modelProvider: { api: "openai-completions" },
};

test("SDK-shaped explicit selection supports AIVAN without message fields", () => {
  assert.equal(harness.supports({ ...supportContext, requestedRuntime: "openclaw-aivan" }).supported, true);
});

test("registration opts out of automatic provider selection", () => {
  assert.deepEqual(harness.autoSelection, { providerIds: [] });
});

test("SDK-shaped auto and other runtime contexts do not select AIVAN", () => {
  for (const requestedRuntime of ["auto", "openclaw", "codex", "another-plugin"]) {
    assert.equal(harness.supports({ ...supportContext, requestedRuntime }).supported, false, requestedRuntime);
  }
});

test("prompt-like extra fields cannot opt another runtime into AIVAN", () => {
  assert.equal(harness.supports({
    ...supportContext,
    requestedRuntime: "auto",
    prompt: "Please source suppliers for an RFQ",
    metadata: { intent: "trade-sourcing" },
  }).supported, false);
});

test("explicit selection does not bypass the per-attempt trade boundary", async () => {
  const originalFetch = globalThis.fetch;
  let coreCalls = 0;
  globalThis.fetch = async () => {
    coreCalls += 1;
    return new Response(JSON.stringify({ status: "ok", reply_text: "Review the pending draft." }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const result = await harness.runAttempt({
      prompt: "What is the weather today?",
      sessionId: "non-trade-selection-regression",
      channel: "weixin",
    });
    assert.equal(coreCalls, 0);
    assert.equal(result.didSendViaMessagingTool, false);
    assert.deepEqual(result.assistantTexts, []);
    assert.deepEqual(result.messagingToolSentTexts, []);
    assert.deepEqual(result.messagingToolSentMediaUrls, []);
    assert.deepEqual(result.messagingToolSentTargets, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("matched trade is forwarded once and remains silent after explicit selection", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), method: init?.method, body: JSON.parse(init?.body ?? "{}") });
    return new Response(JSON.stringify({ status: "ok", reply_text: "Review the pending draft." }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const result = await harness.runAttempt({
      prompt: "Please source suppliers for 5,000 shirts",
      sessionId: "trade-selection-regression",
      senderId: "buyer-selection-regression",
      channel: "weixin",
    });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].method, "POST");
    assert.equal(new URL(requests[0].url).pathname, "/invoke");
    assert.equal(requests[0].body.message_text, "Please source suppliers for 5,000 shirts");
    assert.equal(result.aivanHandled, true);
    assert.equal(result.didSendViaMessagingTool, true);
    assert.equal(result.outboundAuthorization, "required");
    assert.deepEqual(result.assistantTexts, []);
    assert.deepEqual(result.messagingToolSentTexts, []);
    assert.deepEqual(result.messagingToolSentMediaUrls, []);
    assert.deepEqual(result.messagingToolSentTargets, []);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
