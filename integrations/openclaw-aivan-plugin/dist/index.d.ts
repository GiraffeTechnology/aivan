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
/**
 * aivan.health — Ping the local AIVAN server.
 * Returns { healthy: boolean, version?: string }.
 */
export declare function health(): Promise<{
    healthy: boolean;
    version?: string;
    error?: string;
}>;
/**
 * aivan.forwardEvent — Send a normalised OpenClaw event to AIVAN.
 * AIVAN processes the event, may produce pending drafts, but does NOT
 * send any message without human approval.
 */
export declare function forwardEvent(event: {
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
}>;
/**
 * aivan.openDashboard — Return the local dashboard URL.
 * Callers should open this URL in a browser; the plugin does not open
 * browser windows itself.
 */
export declare function openDashboard(): {
    url: string;
};
/**
 * aivan.getPendingDrafts — List outbound drafts awaiting human approval.
 */
export declare function getPendingDrafts(projectId?: string): Promise<{
    drafts: Array<{
        draft_id: string;
        project_id: string;
        channel: string;
        target_role: string;
        message_text: string;
        created_at: string;
    }>;
    error?: string;
}>;
/**
 * aivan.approveDraft — Approve a pending draft for sending.
 * AIVAN will then send the message via OpenClaw. This plugin does NOT
 * send the message itself.
 */
export declare function approveDraft(draftId: string): Promise<{
    approved: boolean;
    draft_id: string;
    error?: string;
}>;
/**
 * aivan.rejectDraft — Reject and discard a pending draft.
 */
export declare function rejectDraft(draftId: string, reason?: string): Promise<{
    rejected: boolean;
    draft_id: string;
    error?: string;
}>;
declare const pluginEntry: any;
export default pluginEntry;
export declare function register(api: any): void;
