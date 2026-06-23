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

import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
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
}): Promise<{ accepted: boolean; project_id?: string; action?: string; error?: string }> {
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
  return {
    accepted: true,
    project_id: String(d["project_id"] ?? ""),
    action: String(d["action"] ?? ""),
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
  return { drafts: (d["drafts"] as drafts) ?? [] };
}

// TypeScript helper — mirrors the drafts array element type
type drafts = Array<{
  draft_id: string;
  project_id: string;
  channel: string;
  target_role: string;
  message_text: string;
  created_at: string;
}>;

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
  const result = await safeFetch(`/api/drafts/${encodeURIComponent(draftId)}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
  });
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
  const result = await safeFetch(`/api/drafts/${encodeURIComponent(draftId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? "rejected by operator" }),
  });
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
// defineToolPlugin with zero tools satisfies the tool-plugin authoring validator.
// The actual channel bridge runs via api.registerInteractiveHandler in register().
export default defineToolPlugin({
  id: "openclaw-aivan",
  name: "AIVAN OpenClaw Bridge",
  description: "OpenClaw bridge for forwarding IM/email/marketplace events to the local AIVAN service with human approval.",
  configSchema: Type.Object(
    { aivanBaseUrl: Type.Optional(Type.String({ default: "http://127.0.0.1:8765" })) },
    { additionalProperties: false }
  ),
  tools: (_tool) => [],
});

// ─── OpenClaw Plugin Entry Point ──────────────────────────────────────────────
export function register(api: any): void {
  if (typeof api.registerInteractiveHandler === "function") {
    // channel: required by PluginInteractiveRegistration — OpenClaw calls .trim() on it
    // namespace: required identifier (previously mis-named as "id", which is not a valid field)
    api.registerInteractiveHandler({
      channel: "openclaw-weixin",
      namespace: "aivan",
      handler: async (ctx: any) => {
        const msg = ctx?.message?.text ?? ctx?.text ?? "";
        const channelId = ctx?.channel ?? ctx?.channelId ?? "openclaw-weixin";
        const senderId = ctx?.senderId ?? ctx?.peer?.id ?? "unknown";
        const convId = ctx?.conversationId ?? ctx?.threadId ?? senderId;
        const accountId = ctx?.accountId ?? ctx?.channelAccountId ?? "";
        // Extract project_id and role_context from ctx — pass through for supplier-reply routing
        const projectId =
          ctx?.metadata?.project_id ?? ctx?.projectId ?? ctx?.project_id ?? null;
        const roleContext =
          ctx?.metadata?.role_context ?? ctx?.roleContext ?? ctx?.role_context ?? null;
        const event: any = {
          source: "openclaw",
          channel: channelId,
          channel_account_id: accountId,
          conversation_id: convId,
          sender_id: senderId,
          sender_display_name: ctx?.peer?.name ?? "",
          message_text: msg,
          message_type: "text",
          attachments: [],
          timestamp: new Date().toISOString(),
          project_id: projectId,
          role_context: roleContext,
          mode: "auto",
        };
        const result: any = await forwardEvent(event);
        if (result?.accepted && result?.reply_text) {
          return { text: result.reply_text };
        }
        return;
      },
    });
  }
}
