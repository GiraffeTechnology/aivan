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

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";

function baseUrl(): string {
  return (
    (typeof process !== "undefined" && process.env?.AIVAN_BASE_URL) ||
    DEFAULT_BASE_URL
  );
}

function apiKey(): string | null {
  return (
    (typeof process !== "undefined" && process.env?.AIVAN_API_KEY) || null
  );
}

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = apiKey();
  if (key) {
    headers["X-AIVAN-API-Key"] = key;
  }
  return headers;
}

async function safeFetch(
  path: string,
  options?: RequestInit
): Promise<{ ok: boolean; status: number; data: unknown }> {
  const url = `${baseUrl()}${path}`;
  try {
    const res = await fetch(url, {
      ...options,
      headers: { ...buildHeaders(), ...(options?.headers ?? {}) },
    });
    const data = res.headers
      .get("content-type")
      ?.includes("application/json")
      ? await res.json()
      : await res.text();
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      data: {
        error: "AIVAN server unreachable",
        detail: err instanceof Error ? err.message : String(err),
      },
    };
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
}> {
  const result = await safeFetch("/api/health");
  if (!result.ok) {
    return {
      healthy: false,
      error:
        typeof result.data === "object" &&
        result.data !== null &&
        "error" in result.data
          ? String((result.data as Record<string, unknown>)["error"])
          : "AIVAN server not available",
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
  role_context?: string | Record<string, unknown> | null;
  mode?: string;
}): Promise<{
  accepted: boolean;
  project_id?: string;
  action?: string;
  reply_text?: string;
  output?: string;
  error?: string;
}> {
  const result = await safeFetch("/api/openclaw/events", {
    method: "POST",
    body: JSON.stringify(event),
  });
  if (!result.ok) {
    const d = result.data as Record<string, unknown>;
    return {
      accepted: false,
      error: String(d["detail"] ?? d["error"] ?? "Event forwarding failed"),
    };
  }
  const d = result.data as Record<string, unknown>;
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
  const result = await safeFetch(`/api/drafts${qs}`);
  if (!result.ok) {
    return { drafts: [], error: "Failed to fetch drafts" };
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
    const d = result.data as Record<string, unknown>;
    return {
      approved: false,
      draft_id: draftId,
      error: String(d["detail"] ?? "Approval failed"),
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
    const d = result.data as Record<string, unknown>;
    return {
      rejected: false,
      draft_id: draftId,
      error: String(d["detail"] ?? "Rejection failed"),
    };
  }
  return { rejected: true, draft_id: draftId };
}

// ─── Plugin metadata export for `openclaw plugins validate` ───────────────────
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractSessionContext(params: any): {
  conversation_id?: string;
  sender_id?: string;
  channel?: string;
  project_id?: string;
  role_context?: string;
} {
  const ctx: {
    conversation_id?: string;
    sender_id?: string;
    channel?: string;
    project_id?: string;
    role_context?: string;
  } = {};

  const sessionId: unknown =
    params?.sessionId ?? params?.session?.id ?? params?.sessionKey;
  if (sessionId != null) ctx.conversation_id = String(sessionId);

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
      supports(_ctx: any): { supported: boolean; reason?: string } {
        return {
          supported: true,
          reason:
            "AIVAN handles trade inquiry / RFQ / supplier-routing messages",
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

          const ctx = extractSessionContext(params);
          const event: Parameters<typeof forwardEvent>[0] = {
            source: "openclaw",
            channel: ctx.channel ?? "openclaw-weixin",
            conversation_id: ctx.conversation_id ?? "unknown",
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
