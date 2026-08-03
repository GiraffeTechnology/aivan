/**
 * OpenClaw plugin bridge for AIVAN.
 *
 * This plugin is a thin HTTP bridge only. It does not:
 *   - store IM/email/marketplace/platform credentials
 *   - bypass login, CAPTCHA, anti-bot, or platform rules
 *   - send outbound messages without AIVAN's human approval gate
 *   - duplicate any AIVAN core business logic
 *
 * All draft approval and rejection actions are forwarded to the local
 * AIVAN API, which enforces the human-approval policy.
 */

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Type } from "typebox";
import { createHash } from "node:crypto";
import intentBoundary from "./intent-boundary.json" with { type: "json" };

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";
const DEFAULT_CONNECT_TIMEOUT_MS = 3_000;
const DEFAULT_READ_TIMEOUT_MS = 15_000;
const DEFAULT_MAX_RETRIES = 1;

type RuntimeConfig = {
  aivanBaseUrl?: string;
  connectTimeoutMs?: number;
  readTimeoutMs?: number;
  maxRetries?: number;
};

type AivanError = {
  code: string;
  message: string;
  retryable: boolean;
  status: number;
};

type FetchPolicy = {
  retryable?: boolean;
  idempotencyKey?: string;
  traceId?: string;
  participantId?: string;
  participantRole?: string;
  participantConversationRole?: string;
};

let registeredConfig: RuntimeConfig = {};

function boundedInteger(
  configValue: number | undefined,
  envName: string,
  fallback: number,
  minimum: number,
  maximum: number
): number {
  const envValue =
    typeof process !== "undefined" ? process.env?.[envName] : undefined;
  const candidate = configValue ?? (envValue ? Number(envValue) : fallback);
  if (!Number.isFinite(candidate)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.trunc(candidate)));
}

function baseUrl(): string {
  const configured =
    registeredConfig.aivanBaseUrl ??
    ((typeof process !== "undefined" && process.env?.AIVAN_BASE_URL) ||
      DEFAULT_BASE_URL);
  return configured.replace(/\/+$/, "");
}

function apiKey(): string | null {
  return (
    (typeof process !== "undefined" && process.env?.AIVAN_API_KEY) || null
  );
}

function buildHeaders(policy: FetchPolicy = {}): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = apiKey();
  if (key) {
    headers["X-AIVAN-API-Key"] = key;
  }
  const trustedEnvironmentHeaders: Array<[string, string]> = [
    ["AIVAN_TENANT_ID", "X-AIVAN-Tenant-ID"],
    ["AIVAN_ACTOR_ID", "X-AIVAN-Actor-ID"],
    ["AIVAN_ROLE_CONTEXT", "X-AIVAN-Role-Context"],
    ["AIVAN_CONVERSATION_ROLE", "X-AIVAN-Conversation-Role"],
    ["AIVAN_EXECUTION_MODE", "X-AIVAN-Execution-Mode"],
    ["AIVAN_CHANNEL_ACCOUNT_ID", "X-AIVAN-Channel-Account-ID"],
  ];
  for (const [environmentName, headerName] of trustedEnvironmentHeaders) {
    const value =
      typeof process !== "undefined"
        ? process.env?.[environmentName]?.trim()
        : undefined;
    if (value) headers[headerName] = value;
  }
  if (policy.idempotencyKey) {
    headers["Idempotency-Key"] = policy.idempotencyKey;
  }
  if (policy.traceId) {
    headers["X-AIVAN-Trace-ID"] = policy.traceId;
  }
  if (policy.participantId) {
    headers["X-AIVAN-Participant-ID"] = policy.participantId;
  }
  if (policy.participantRole) {
    headers["X-AIVAN-Participant-Role"] = policy.participantRole;
  }
  if (policy.participantConversationRole) {
    headers["X-AIVAN-Participant-Conversation-Role"] = policy.participantConversationRole;
  }
  return headers;
}

function participantIdentity(event: {
  channel: string;
  channel_account_id?: string;
  sender_id: string;
  business_role?: string;
  role_context?: string | Record<string, unknown> | null;
  conversation_role?: string;
}): { id: string; role: string; conversationRole: string } {
  const rawRole = String(
    event.business_role ??
      (typeof event.role_context === "string" ? event.role_context : "buyer")
  ).trim().toLowerCase();
  const roleAliases: Record<string, string> = {
    customer: "buyer", b_side: "buyer", buyer: "buyer",
    seller: "supplier", m_side: "supplier", supplier: "supplier",
    operator: "sales", user: "sales", salesperson: "sales", sales: "sales",
  };
  const role = roleAliases[rawRole] ?? "buyer";
  const conversationRole = event.conversation_role ??
    (role === "buyer" ? "buyer_thread" : role === "supplier" ? "supplier_thread" : "internal_thread");
  const participantKey = [event.channel, event.channel_account_id ?? "default", event.sender_id].join("\u001f");
  const id = `ocp_${createHash("sha256").update(participantKey).digest("hex").slice(0, 48)}`;
  return { id, role, conversationRole };
}

function errorMessage(data: unknown): string {
  if (typeof data === "string" && data.trim()) return data.trim();
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    const detail = record["detail"];
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (detail && typeof detail === "object") {
      const nested = detail as Record<string, unknown>;
      if (nested["message"]) return String(nested["message"]);
      if (nested["reason"]) return String(nested["reason"]);
      if (nested["error"]) return String(nested["error"]);
    }
    if (record["message"]) return String(record["message"]);
    if (record["error"]) {
      const error = record["error"];
      if (error && typeof error === "object") {
        const nested = error as Record<string, unknown>;
        return String(nested["message"] ?? nested["code"] ?? "AIVAN request failed");
      }
      return String(error);
    }
  }
  return "AIVAN request failed";
}

function mapError(status: number, data: unknown, timeoutKind?: string): AivanError {
  if (timeoutKind) {
    return {
      code: timeoutKind === "connect" ? "AIVAN_CONNECT_TIMEOUT" : "AIVAN_READ_TIMEOUT",
      message:
        timeoutKind === "connect"
          ? "AIVAN did not accept the connection in time. Check the local service."
          : "AIVAN took too long to return a response. The action was not retried unless it was idempotent.",
      retryable: true,
      status: 0,
    };
  }
  const mappings: Record<number, [string, string, boolean]> = {
    0: ["AIVAN_UNREACHABLE", "AIVAN is unreachable. Check AIVAN_BASE_URL and service health.", true],
    400: ["AIVAN_INVALID_REQUEST", "AIVAN rejected the request contract.", false],
    401: ["AIVAN_AUTH_REQUIRED", "AIVAN authentication is required.", false],
    403: ["AIVAN_FORBIDDEN", "The authenticated actor is not authorized for this AIVAN action.", false],
    404: ["AIVAN_NOT_FOUND", "The requested AIVAN resource was not found.", false],
    409: ["AIVAN_STATE_CONFLICT", "The AIVAN resource changed state; refresh before retrying.", false],
    429: ["AIVAN_RATE_LIMITED", "AIVAN is temporarily rate limited.", true],
    502: ["AIVAN_BAD_GATEWAY", "AIVAN dependency gateway failed.", true],
    503: ["AIVAN_UNAVAILABLE", "AIVAN is temporarily unavailable or misconfigured.", true],
    504: ["AIVAN_GATEWAY_TIMEOUT", "AIVAN dependency gateway timed out.", true],
  };
  const mapped = mappings[status] ?? [
    status >= 500 ? "AIVAN_SERVER_ERROR" : "AIVAN_REQUEST_FAILED",
    errorMessage(data),
    status >= 500,
  ];
  return {
    code: String(mapped[0]),
    message: `${String(mapped[1])} ${errorMessage(data)}`.trim(),
    retryable: Boolean(mapped[2]),
    status,
  };
}

function shouldRetry(error: AivanError, policy: FetchPolicy, attempt: number): boolean {
  const maxRetries = boundedInteger(
    registeredConfig.maxRetries,
    "AIVAN_MAX_RETRIES",
    DEFAULT_MAX_RETRIES,
    0,
    2
  );
  return Boolean(policy.retryable && error.retryable && attempt < maxRetries);
}

async function delay(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function safeFetch(
  path: string,
  options?: RequestInit,
  policy: FetchPolicy = {}
): Promise<{ ok: boolean; status: number; data: unknown; error?: AivanError }> {
  const url = `${baseUrl()}${path}`;
  let attempt = 0;
  while (true) {
    const controller = new AbortController();
    let timeoutKind: "connect" | "read" | undefined;
    const connectTimeout = boundedInteger(
      registeredConfig.connectTimeoutMs,
      "AIVAN_CONNECT_TIMEOUT_MS",
      DEFAULT_CONNECT_TIMEOUT_MS,
      100,
      30_000
    );
    const readTimeout = boundedInteger(
      registeredConfig.readTimeoutMs,
      "AIVAN_READ_TIMEOUT_MS",
      DEFAULT_READ_TIMEOUT_MS,
      500,
      120_000
    );
    const connectTimer = setTimeout(() => {
      timeoutKind = "connect";
      controller.abort();
    }, connectTimeout);
    try {
      const res = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: { ...buildHeaders(policy), ...(options?.headers ?? {}) },
      });
      clearTimeout(connectTimer);
      const readTimer = setTimeout(() => {
        timeoutKind = "read";
        controller.abort();
      }, readTimeout);
      let data: unknown;
      try {
        data = res.headers.get("content-type")?.includes("application/json")
          ? await res.json()
          : await res.text();
      } finally {
        clearTimeout(readTimer);
      }
      if (res.ok) return { ok: true, status: res.status, data };
      const mapped = mapError(res.status, data);
      if (shouldRetry(mapped, policy, attempt)) {
        attempt += 1;
        await delay(200 * 2 ** (attempt - 1));
        continue;
      }
      return { ok: false, status: res.status, data, error: mapped };
    } catch (err) {
      clearTimeout(connectTimer);
      const mapped = timeoutKind
        ? mapError(0, null, timeoutKind)
        : mapError(0, {
            error: err instanceof Error ? err.message : String(err),
          });
      if (shouldRetry(mapped, policy, attempt)) {
        attempt += 1;
        await delay(200 * 2 ** (attempt - 1));
        continue;
      }
      return {
        ok: false,
        status: 0,
        data: { error: mapped.message },
        error: mapped,
      };
    }
  }
}

/**
 * aivan.health — Ping the local AIVAN server.
 * Returns { healthy: boolean, version?: string }.
 */
export async function health(): Promise<{
  healthy: boolean;
  version?: string;
  error?: string;
  error_code?: string;
  retryable?: boolean;
}> {
  const result = await safeFetch("/api/health", undefined, { retryable: true });
  if (!result.ok) {
    return {
      healthy: false,
      error: result.error?.message ?? "AIVAN server not available",
      error_code: result.error?.code,
      retryable: result.error?.retryable,
    };
  }
  const d = result.data as Record<string, unknown>;
  return { healthy: true, version: String(d["version"] ?? "unknown") };
}

/**
 * aivan.forwardEvent — Send a normalised OpenClaw event to AIVAN.
 * AIVAN processes the event, may produce pending drafts, but does NOT
 * send any message without human approval.
 */
export async function forwardEvent(event: {
  source?: string;
  channel: string;
  channel_account_id?: string;
  conversation_id: string;
  message_id?: string;
  sender_id: string;
  sender_display_name?: string;
  message_text: string;
  message_type?: string;
  attachments?: unknown[];
  timestamp?: string;
  project_id?: string;
  tenant_id?: string;
  source_trace_id?: string;
  idempotency_key?: string;
  actor_id?: string;
  business_role?: string;
  conversation_role?: string;
  execution_mode?: string;
  role_context?: string | Record<string, unknown> | null;
  mode?: string;
}): Promise<{
  accepted: boolean;
  project_id?: string;
  action?: string;
  reply_text?: string;
  output?: string;
  error?: string;
  error_code?: string;
  retryable?: boolean;
}> {
  const stableIdentity = [
    event.source ?? "openclaw",
    event.channel,
    event.channel_account_id ?? "default",
    event.conversation_id,
    event.message_id ?? event.message_text,
  ].join("\u001f");
  const idempotencyKey =
    event.idempotency_key ??
    `oc_${createHash("sha256").update(stableIdentity).digest("hex").slice(0, 48)}`;
  const participant = participantIdentity(event);
  const result = await safeFetch(
    "/invoke",
    {
      method: "POST",
      body: JSON.stringify({ ...event, idempotency_key: idempotencyKey }),
    },
    {
      retryable: true,
      idempotencyKey,
      traceId: event.source_trace_id,
      participantId: participant.id,
      participantRole: participant.role,
      participantConversationRole: participant.conversationRole,
    }
  );
  if (!result.ok) {
    return {
      accepted: false,
      error: result.error?.message ?? "Event forwarding failed",
      error_code: result.error?.code,
      retryable: result.error?.retryable,
    };
  }
  const d = result.data as Record<string, unknown>;
  if (d["status"] === "error") {
    const failSoft = mapError(503, d);
    const degradedReply = d["reply_text"]
      ? String(d["reply_text"])
      : d["output"]
        ? String(d["output"])
        : undefined;
    return {
      accepted: false,
      reply_text: degradedReply,
      output: d["output"] ? String(d["output"]) : undefined,
      error: errorMessage(d),
      error_code: String(d["error_code"] ?? failSoft.code),
      retryable: Boolean(d["retryable"] ?? failSoft.retryable),
    };
  }
  const replyText = d["reply_text"]
    ? String(d["reply_text"])
    : d["output"]
      ? String(d["output"])
      : undefined;
  process.stderr.write(
    `[aivan] AIVAN HTTP status=${result.status} fields=${JSON.stringify({
      status: d["status"],
      output: d["output"] ? String(d["output"]).slice(0, 120) : undefined,
      reply_text: d["reply_text"] ? String(d["reply_text"]).slice(0, 120) : undefined,
    })}\n`
  );
  return {
    accepted: true,
    project_id: d["project_id"] ? String(d["project_id"]) : undefined,
    action: d["action"] ? String(d["action"]) : undefined,
    reply_text: replyText,
    output: d["output"] ? String(d["output"]) : undefined,
  };
}

/**
 * aivan.openDashboard — Return the local dashboard URL.
 * Callers should open this URL in a browser; the plugin does not open
 * browser windows itself.
 */
export function openDashboard(): { url: string } {
  return { url: `${baseUrl()}/app` };
}

/**
 * aivan.getPendingDrafts — List outbound drafts awaiting human approval.
 */
export async function getPendingDrafts(projectId?: string): Promise<{
  drafts: Array<{
    draft_id: string;
    project_id: string;
    channel: string;
    target_role: string;
    message_text: string;
    created_at: string;
  }>;
  error?: string;
}> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const result = await safeFetch(`/api/drafts${qs}`, undefined, {
    retryable: true,
  });
  if (!result.ok) {
    return { drafts: [], error: result.error?.message ?? "Failed to fetch drafts" };
  }
  const d = result.data as Record<string, unknown>;
  return { drafts: (d["drafts"] as DraftItem[]) ?? [] };
}

type DraftItem = {
  draft_id: string;
  project_id: string;
  channel: string;
  target_role: string;
  message_text: string;
  created_at: string;
};

/**
 * aivan.approveDraft — Approve a pending draft for sending.
 * AIVAN will then send the message via OpenClaw. This plugin does NOT
 * send the message itself.
 */
export async function approveDraft(draftId: string): Promise<{
  approved: boolean;
  draft_id: string;
  error?: string;
}> {
  const result = await safeFetch(
    `/api/drafts/${encodeURIComponent(draftId)}/approve`,
    {
      method: "POST",
      body: JSON.stringify({}),
    }
  );
  if (!result.ok) {
    return {
      approved: false,
      draft_id: draftId,
      error: result.error?.message ?? "Approval failed",
    };
  }
  return { approved: true, draft_id: draftId };
}

/**
 * aivan.rejectDraft — Reject and discard a pending draft.
 */
export async function rejectDraft(
  draftId: string,
  reason?: string
): Promise<{ rejected: boolean; draft_id: string; error?: string }> {
  const result = await safeFetch(
    `/api/drafts/${encodeURIComponent(draftId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? "rejected by operator" }),
    }
  );
  if (!result.ok) {
    return {
      rejected: false,
      draft_id: draftId,
      error: result.error?.message ?? "Rejection failed",
    };
  }
  return { rejected: true, draft_id: draftId };
}

// ─── Plugin metadata export for `openclaw plugins validate` ───────────────────
function toolResult(details: unknown): {
  content: Array<{ type: "text"; text: string }>;
  details: unknown;
} {
  return {
    content: [{ type: "text", text: JSON.stringify(details, null, 2) }],
    details,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function registerAivanTools(api: any): number {
  if (typeof api?.registerTool !== "function") return 0;
  const registrations: Array<[any, { optional?: boolean } | undefined]> = [
    [{ name: "aivan.health", description: "Check whether the configured AIVAN Core service is healthy.", parameters: Type.Object({}, { additionalProperties: false }), async execute() { return toolResult(await health()); } }, undefined],
    [{
      name: "aivan.forwardEvent",
      description: "Forward a trade-sourcing event to AIVAN Core. Idempotent retries are bounded and outbound drafts still require human approval.",
      parameters: Type.Object({
        channel: Type.String(), conversation_id: Type.String(), sender_id: Type.String(), message_text: Type.String(),
        source: Type.Optional(Type.String()), channel_account_id: Type.Optional(Type.String()), message_id: Type.Optional(Type.String()),
        sender_display_name: Type.Optional(Type.String()), message_type: Type.Optional(Type.String()), attachments: Type.Optional(Type.Array(Type.Unknown())),
        timestamp: Type.Optional(Type.String()), project_id: Type.Optional(Type.String()), tenant_id: Type.Optional(Type.String()),
        source_trace_id: Type.Optional(Type.String()), idempotency_key: Type.Optional(Type.String()), actor_id: Type.Optional(Type.String()),
        business_role: Type.Optional(Type.String()), conversation_role: Type.Optional(Type.String()), execution_mode: Type.Optional(Type.String()),
        role_context: Type.Optional(Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown()), Type.Null()])), mode: Type.Optional(Type.String()),
      }, { additionalProperties: false }),
      async execute(_id: string, params: Parameters<typeof forwardEvent>[0]) { return toolResult(await forwardEvent(params)); },
    }, undefined],
    [{ name: "aivan.openDashboard", description: "Return the local AIVAN dashboard URL without opening a browser.", parameters: Type.Object({}, { additionalProperties: false }), async execute() { return toolResult(openDashboard()); } }, undefined],
    [{ name: "aivan.getPendingDrafts", description: "List outbound AIVAN drafts still awaiting human approval.", parameters: Type.Object({ project_id: Type.Optional(Type.String()) }, { additionalProperties: false }), async execute(_id: string, params: { project_id?: string }) { return toolResult(await getPendingDrafts(params.project_id)); } }, undefined],
    [{ name: "aivan.approveDraft", description: "Submit an explicit human approval decision to AIVAN Core; the plugin cannot send directly or bypass authorization.", parameters: Type.Object({ draft_id: Type.String() }, { additionalProperties: false }), async execute(_id: string, params: { draft_id: string }) { return toolResult(await approveDraft(params.draft_id)); } }, { optional: true }],
    [{ name: "aivan.rejectDraft", description: "Reject a pending AIVAN draft with an optional operator reason.", parameters: Type.Object({ draft_id: Type.String(), reason: Type.Optional(Type.String()) }, { additionalProperties: false }), async execute(_id: string, params: { draft_id: string; reason?: string }) { return toolResult(await rejectDraft(params.draft_id, params.reason)); } }, { optional: true }],
  ];
  for (const [descriptor, options] of registrations) {
    options ? api.registerTool(descriptor, options) : api.registerTool(descriptor);
  }
  return registrations.length;
}

const pluginEntry: any = definePluginEntry({
  id: "openclaw-aivan",
  name: "AIVAN OpenClaw Bridge",
  description:
    "OpenClaw bridge for forwarding IM/email/marketplace events to the local AIVAN service with human approval.",
  configSchema: Type.Object(
    {
      aivanBaseUrl: Type.Optional(
        Type.String({ default: "http://127.0.0.1:8765" })
      ),
      connectTimeoutMs: Type.Optional(Type.Integer({ minimum: 100, maximum: 30000, default: 3000 })),
      readTimeoutMs: Type.Optional(Type.Integer({ minimum: 500, maximum: 120000, default: 15000 })),
      maxRetries: Type.Optional(Type.Integer({ minimum: 0, maximum: 2, default: 1 })),
    },
    { additionalProperties: false }
  ),
  register,
} as any);

export default pluginEntry;

// ─── AgentHarness helpers ─────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractPrompt(params: any): string {
  const candidates: unknown[] = [
    params?.prompt,
    params?.input,
    params?.message?.text,
    params?.userMessage?.text,
    params?.session?.latestUserMessage?.text,
    params?.session?.prompt,
  ];
  return (
    candidates.find((v) => typeof v === "string" && (v as string).trim().length > 0) as string | undefined
  )?.trim() ?? "";
}

// This is the single runtime boundary consumed by both supports() and
// runAttempt(). The SKILL artifact references the same JSON contract.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function isTradeSourcingIntent(params: any): boolean {
  const structured = String(
    params?.metadata?.intent ?? params?.intent ?? ""
  ).toLowerCase();
  if (intentBoundary.structuredIntents.includes(structured)) return true;

  const role = String(
    params?.metadata?.business_role ??
      params?.metadata?.role_context ??
      params?.business_role ??
      params?.role_context ??
      ""
  ).toLowerCase();
  const projectId = params?.metadata?.project_id ?? params?.project_id;
  if (projectId && intentBoundary.businessRoles.includes(role)) return true;

  const normalizedPrompt = extractPrompt(params).toLowerCase();
  return Object.values(intentBoundary.routingTerms)
    .flat()
    .some((term) => normalizedPrompt.includes(term.toLowerCase()));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractSessionContext(params: any): {
  conversation_id?: string;
  message_id?: string;
  sender_id?: string;
  channel?: string;
  project_id?: string;
  role_context?: string;
} {
  const ctx: {
    conversation_id?: string;
    message_id?: string;
    sender_id?: string;
    channel?: string;
    project_id?: string;
    role_context?: string;
  } = {};

  const sessionId: unknown =
    params?.sessionId ?? params?.session?.id ?? params?.sessionKey;
  if (sessionId != null) ctx.conversation_id = String(sessionId);

  const messageId: unknown =
    params?.messageId ??
    params?.message?.id ??
    params?.event?.message_id ??
    params?.metadata?.message_id ??
    params?.session?.latestUserMessage?.id;
  if (messageId != null) ctx.message_id = String(messageId);

  const senderId: unknown =
    params?.senderId ??
    params?.sender?.id ??
    params?.peerId ??
    params?.session?.peerId;
  if (senderId != null) ctx.sender_id = String(senderId);

  const channel: unknown =
    params?.messageChannel ??
    params?.channelId ??
    params?.channel ??
    params?.messageProvider;
  if (channel != null) ctx.channel = String(channel);

  const projectId: unknown =
    params?.metadata?.project_id ?? params?.project_id;
  if (projectId != null) ctx.project_id = String(projectId);

  const roleContext: unknown =
    params?.metadata?.role_context ?? params?.role_context;
  if (roleContext != null) ctx.role_context = String(roleContext);

  return ctx;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildSuccessResult(params: any, replyText: string): any {
  const sessionId: string = typeof params?.sessionId === "string" ? params.sessionId : "";
  const now = Date.now();
  const prompt = extractPrompt(params);

  const assistantMsg = {
    role: "assistant",
    content: [{ type: "text", text: replyText }],
    api: "aivan",
    provider: "aivan",
    model: "aivan",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "stop",
    timestamp: now,
  };

  const messagesSnapshot: unknown[] = [];
  if (prompt) {
    messagesSnapshot.push({ role: "user", content: prompt, timestamp: now - 1 });
  }
  messagesSnapshot.push(assistantMsg);

  return {
    aborted: false,
    externalAbort: false,
    timedOut: false,
    idleTimedOut: false,
    timedOutDuringCompaction: false,
    promptError: null,
    promptErrorSource: null,
    sessionIdUsed: sessionId,
    messagesSnapshot,
    assistantTexts: [replyText],
    toolMetas: [],
    lastAssistant: assistantMsg,
    didSendViaMessagingTool: false,
    messagingToolSentTexts: [],
    messagingToolSentMediaUrls: [],
    messagingToolSentTargets: [],
    cloudCodeAssistFormatError: false,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildPassThroughResult(params: any): any {
  const sessionId: string = typeof params?.sessionId === "string" ? params.sessionId : "";
  return {
    aborted: false,
    externalAbort: false,
    timedOut: false,
    idleTimedOut: false,
    timedOutDuringCompaction: false,
    promptError: null,
    promptErrorSource: null,
    sessionIdUsed: sessionId,
    messagesSnapshot: [],
    assistantTexts: [],
    toolMetas: [],
    lastAssistant: undefined,
    didSendViaMessagingTool: false,
    messagingToolSentTexts: [],
    messagingToolSentMediaUrls: [],
    messagingToolSentTargets: [],
    cloudCodeAssistFormatError: false,
  };
}

// ─── OpenClaw Plugin Entry Point ──────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function register(api: any): void {
  try {
    registeredConfig = (api?.pluginConfig ?? api?.config ?? {}) as RuntimeConfig;
    const toolCount = registerAivanTools(api);
    process.stderr.write(`[aivan] registered ${toolCount} Gateway tools\n`);

    if (typeof api?.registerAgentHarness !== "function") {
      process.stderr.write(
        "[aivan] registerAgentHarness not available (api keys: " +
          JSON.stringify(Object.keys(api ?? {})) +
          ")\n"
      );
      return;
    }

    api.registerAgentHarness({
      id: "openclaw-aivan",
      label: "AIVAN Agent Harness",

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      supports(ctx: any): { supported: boolean; reason?: string } {
        const supported = isTradeSourcingIntent(ctx);
        return {
          supported,
          reason: supported
            ? "Matched the shared AIVAN trade-sourcing intent boundary."
            : "Non-trade message: explicit pass-through to the next OpenClaw harness.",
        };
      },

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      async runAttempt(params: any): Promise<any> {
        try {
          const prompt = extractPrompt(params);

          if (!prompt) {
            process.stderr.write(
              "[aivan] runAttempt: no prompt found in params, returning pass-through\n"
            );
            return buildPassThroughResult(params);
          }

          if (!isTradeSourcingIntent(params)) {
            process.stderr.write(
              "[aivan] runAttempt: outside trade-sourcing boundary, returning pass-through\n"
            );
            return buildPassThroughResult(params);
          }

          const ctx = extractSessionContext(params);
          const stableMessageId =
            ctx.message_id ??
            `ocmsg_${createHash("sha256")
              .update(
                [
                  ctx.channel ?? "openclaw-weixin",
                  ctx.conversation_id ?? "unknown",
                  ctx.sender_id ?? "unknown",
                  prompt,
                ].join("\u001f")
              )
              .digest("hex")
              .slice(0, 48)}`;
          const event: Parameters<typeof forwardEvent>[0] = {
            source: "openclaw",
            channel: ctx.channel ?? "openclaw-weixin",
            conversation_id: ctx.conversation_id ?? "unknown",
            message_id: stableMessageId,
            sender_id: ctx.sender_id ?? "unknown",
            message_text: prompt,
            message_type: "text",
            attachments: [],
            timestamp: new Date().toISOString(),
            mode: "auto",
            ...(ctx.project_id != null ? { project_id: ctx.project_id } : {}),
            ...(ctx.role_context != null
              ? { role_context: ctx.role_context }
              : {}),
          };

          process.stderr.write(
            `[aivan] forwarding event: prompt_len=${prompt.length} session=${ctx.conversation_id ?? "?"}\n`
          );

          let result: Awaited<ReturnType<typeof forwardEvent>>;
          try {
            result = await forwardEvent(event);
          } catch (fetchErr) {
            process.stderr.write(
              `[aivan] AIVAN fetch error: ${String(fetchErr)}\n`
            );
            return buildPassThroughResult(params);
          }

          if (!result.accepted) {
            process.stderr.write(
              `[aivan] AIVAN did not accept event: ${result.error ?? "no reason"}\n`
            );
            if (result.reply_text) {
              return buildSuccessResult(params, result.reply_text);
            }
            return buildPassThroughResult(params);
          }

          const replyText =
            result.reply_text ??
            (result.project_id
              ? `已处理请求 (项目: ${result.project_id})`
              : "已收到您的请求");

          process.stderr.write(
            `[aivan] AIVAN reply: ${replyText.slice(0, 80)}\n`
          );
          return buildSuccessResult(params, replyText);
        } catch (err) {
          process.stderr.write(
            `[aivan] runAttempt unexpected error: ${String(err)}\n`
          );
          return buildPassThroughResult(params);
        }
      },
    });

    process.stderr.write(
      "[aivan] registerAgentHarness registered successfully\n"
    );
  } catch (err) {
    process.stderr.write(`[aivan] register() error: ${String(err)}\n`);
  }
}

