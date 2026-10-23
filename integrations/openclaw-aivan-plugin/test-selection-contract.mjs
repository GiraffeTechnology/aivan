/** Regression coverage for the public OpenClaw AgentHarness selection contract. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { approveDraft, register } from "./dist/index.js";

let harness;
const tools = new Map();
register({
  registerTool(value) { tools.set(value.name, value); },
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

test("approval tool exposes an optional, format-bound reviewed preview", () => {
  const schema = tools.get("aivan.approveDraft").parameters;
  assert.equal(schema.properties.preview_id.type, "string");
  assert.equal(schema.properties.preview_id.pattern, "^render_[a-f0-9]{32}$");
  assert.equal(schema.properties.preview_id.minLength, 39);
  assert.equal(schema.properties.preview_id.maxLength, 39);
  assert.equal(schema.required.includes("preview_id"), false, "Retain the existing English approval contract");
  assert.equal(schema.additionalProperties, false);
});

test("approval tool forwards exactly the human-reviewed preview without fetching or approving another", async () => {
  const previous = globalThis.fetch;
  const requests = [];
  const preview = "render_" + "a".repeat(32);
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), method: init.method, body: JSON.parse(init.body) });
    return new Response(JSON.stringify({ status: "approved_pending_send", sent: false, relay_required: true }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  try {
    const result = await tools.get("aivan.approveDraft").execute("explicit-human-action", {
      draft_id: "draft-1", preview_id: preview,
    });
    assert.equal(result.details.approved, true);
    assert.equal(requests.length, 1);
    assert.equal(new URL(requests[0].url).pathname, "/api/drafts/draft-1/approve");
    assert.equal(requests[0].method, "POST");
    assert.deepEqual(requests[0].body, { preview_id: preview });
  } finally {
    globalThis.fetch = previous;
  }
});

for (const preview of ["", "render_" + "x".repeat(32), "../preview", "审阅", null, 42,
                       "render_" + "a".repeat(32) + "\n", "render_" + "a".repeat(32) + "\r\n"]) {
  test(`invalid approval preview ${JSON.stringify(preview)} fails without any HTTP call`, async () => {
    const previous = globalThis.fetch;
    let calls = 0;
    globalThis.fetch = async () => { calls += 1; throw new Error("Unexpected request"); };
    try {
      const result = await approveDraft("draft-1", preview);
      assert.equal(calls, 0);
      assert.equal(result.approved, false);
      assert.equal(result.error, "AIVAN_INVALID_PREVIEW_ID");
    } finally {
      globalThis.fetch = previous;
    }
  });
}

test("omitting preview retains the existing English request and never fabricates an ID", async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init) => {
    requests.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ status: "approved" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  };
  try {
    assert.equal((await approveDraft("draft-1")).approved, true);
    assert.deepEqual(requests, [{}]);
  } finally {
    globalThis.fetch = previous;
  }
});

for (const status of [403, 409, 503]) {
  test(`Core approval denial ${status} is not retried and cannot trigger automatic preview refresh`, async () => {
    const previous = globalThis.fetch;
    const requests = [];
    globalThis.fetch = async (url, init) => {
      requests.push({ path: new URL(url).pathname, body: JSON.parse(init.body) });
      return new Response(JSON.stringify({ detail: { error: "CONTROLLED_APPROVAL_DENIAL" } }), {
        status, headers: { "Content-Type": "application/json" },
      });
    };
    try {
      const preview = "render_" + "b".repeat(32);
      assert.equal((await approveDraft("draft-1", preview)).approved, false);
      assert.deepEqual(requests, [{ path: "/api/drafts/draft-1/approve", body: { preview_id: preview } }]);
    } finally {
      globalThis.fetch = previous;
    }
  });
}
