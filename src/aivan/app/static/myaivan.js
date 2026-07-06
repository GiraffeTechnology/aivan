/* myaivan conversation page controller.
 *
 * Product boundaries enforced here:
 *  - No direct IM sending: IM drafts only offer Copy → user pastes manually → ✅.
 *  - ✉️ sends email ONLY through the backend adapter (aivan-openclaw or mock),
 *    always behind an explicit confirmation modal.
 *  - Mock email results are labeled as mock, never as real delivery.
 *
 * All user-visible strings resolve through MyaivanI18n.t(); the language
 * switcher only exposes catalogs that are available in production.
 */
(function () {
  "use strict";

  const API = "/api/myaivan";
  const CASE_KEY = "myaivan.activeCaseId";
  const LAYOUT_KEY = "myaivan.layoutHeights";
  const API_KEY_KEY = "myaivan.apiKey";
  const EMAIL_API_KEY_KEY = "myaivan.emailApiKey";
  const LAST_BACKUP_KEY = "myaivan.lastBackup";
  const LAST_BACKUP_RESTORED_KEY = "myaivan.lastBackupRestoredAt";
  const AUTO_BACKUP_INTERVAL_MS = 10 * 60 * 1000;
  const emailStatus = document.body.dataset.emailStatus || "not_configured";
  const emailConfig = {
    status: emailStatus,
    provider: document.body.dataset.emailProvider || emailStatus,
    accountEmail: (document.body.dataset.emailAccount || "").trim().toLowerCase(),
    loginEmail: (document.body.dataset.emailLogin || "").trim().toLowerCase(),
    smtpConfigured: document.body.dataset.emailSmtpConfigured === "true",
    pop3Configured: document.body.dataset.emailPop3Configured === "true",
    loginEmailMatches: document.body.dataset.emailLoginMatches === "true",
    passwordConfigured: document.body.dataset.emailPasswordConfigured === "true",
    requiresApiKey: document.body.dataset.emailRequiresApiKey === "true",
  };

  const stream = document.getElementById("conversation-stream");
  const review = document.getElementById("review-area");
  const inputbar = document.querySelector(".mv-inputbar");
  const draftCards = document.getElementById("draft-cards");
  const input = document.getElementById("message-input");
  const statusLine = document.getElementById("status-line");

  let activeCaseId = null;
  let pendingEmailDraftId = null;
  let lastState = null;
  let authFailureHandled = false;

  function t(key, fallback) {
    return (window.MyaivanI18n && window.MyaivanI18n.t(key, fallback)) || fallback || key;
  }

  function setStatus(text) { statusLine.textContent = text || ""; }

  function storedApiKey() {
    try { return (localStorage.getItem(API_KEY_KEY) || "").trim(); } catch (e) { return ""; }
  }

  function storedEmailApiKey() {
    try { return (localStorage.getItem(EMAIL_API_KEY_KEY) || "").trim(); } catch (e) { return ""; }
  }

  function realEmailReady() {
    return emailConfig.status === "configured"
      && emailConfig.smtpConfigured
      && emailConfig.pop3Configured
      && emailConfig.loginEmailMatches
      && (emailConfig.passwordConfigured || !!storedEmailApiKey());
  }

  function emailReadinessMessage() {
    if (realEmailReady()) {
      return t("settings.email_ready", "Email ready") + ": " + (emailConfig.accountEmail || "");
    }
    if (emailConfig.status !== "configured") {
      return t("settings.email_mode_missing", "Real email mode is not configured.");
    }
    if (!emailConfig.smtpConfigured) {
      return t("settings.email_smtp_missing", "SMTP sending settings are incomplete.");
    }
    if (!emailConfig.pop3Configured) {
      return t("settings.email_pop3_missing", "POP3 receiving settings are incomplete.");
    }
    if (!emailConfig.loginEmailMatches) {
      return t("settings.email_login_mismatch", "Login email must match the configured mailbox.");
    }
    if (!emailConfig.passwordConfigured && !storedEmailApiKey()) {
      return t("settings.email_key_missing", "Save the email sending API Key to enable Email.");
    }
    return t("settings.email_not_ready", "Email is not ready.");
  }

  function authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    const key = storedApiKey();
    if (key) headers["X-AIVAN-API-Key"] = key;
    return headers;
  }

  function downloadText(filename, text) {
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function rememberBackup(markdown, reason) {
    try {
      localStorage.setItem(LAST_BACKUP_KEY, JSON.stringify({
        caseId: activeCaseId || "",
        markdown: markdown || "",
        reason: reason || "backup",
        savedAt: new Date().toISOString(),
      }));
    } catch (e) { /* ignore */ }
  }

  function restoreLastBackupIntoInput() {
    if (input.value.trim()) return;
    try {
      const backup = JSON.parse(localStorage.getItem(LAST_BACKUP_KEY) || "null");
      if (!backup || !backup.markdown || !backup.savedAt) return;
      if (localStorage.getItem(LAST_BACKUP_RESTORED_KEY) === backup.savedAt) return;
      input.value = backup.markdown;
      localStorage.setItem(LAST_BACKUP_RESTORED_KEY, backup.savedAt);
      setStatus(t("status.backup_loaded", "Last backup loaded into the input box. Review it before sending."));
    } catch (e) { /* ignore */ }
  }

  function backupMarkdownFromState(reason) {
    const state = lastState || {};
    const c = state.case || {};
    const lines = [
      "# MyAIVAN Local Backup",
      "",
      "- Reason: " + (reason || "manual"),
      "- Case ID: " + (c.id || activeCaseId || "unknown"),
      "- Title: " + (c.title || ""),
      "- Status: " + (c.status || ""),
      "- Exported at: " + new Date().toISOString(),
      "",
      "## Messages",
      "",
    ];
    (state.messages || []).forEach((m) => {
      lines.push("### " + (m.role || "message") + " / " + (m.type || "text"));
      lines.push((m.createdAt || "") + "");
      lines.push("");
      lines.push(m.content || "");
      lines.push("");
    });
    lines.push("## Outbound Drafts", "");
    (state.outboundDrafts || []).forEach((d) => {
      lines.push("### " + (d.channel || "draft") + " / " + (d.status || ""));
      if (d.recipient) lines.push("- To: " + d.recipient);
      if (d.subject) lines.push("- Subject: " + d.subject);
      lines.push("");
      lines.push(d.body || "");
      lines.push("");
    });
    return lines.join("\n");
  }

  function backupFromLastState(reason) {
    if (!lastState && !activeCaseId) return false;
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const markdown = backupMarkdownFromState(reason);
    rememberBackup(markdown, reason || "local fallback");
    downloadText("myaivan-autobackup-" + (activeCaseId || "unknown") + "-" + stamp + ".md",
      markdown);
    return true;
  }

  function handleAuthFailure() {
    if (authFailureHandled) throw new Error("authentication required");
    authFailureHandled = true;
    backupFromLastState("authentication lost");
    window.location.href = "/myaivan/login";
    throw new Error("authentication required");
  }

  async function api(path, options) {
    const opts = Object.assign({}, options || {});
    opts.headers = authHeaders(Object.assign({ "Content-Type": "application/json" }, opts.headers || {}));
    const resp = await fetch(API + path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, opts));
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401 || resp.status === 403) handleAuthFailure();
    if (!resp.ok) {
      throw new Error((data && data.detail) || ("Request failed: " + resp.status));
    }
    return data;
  }

  // ── rendering ──────────────────────────────────────────────────────────────

  function bubble(message) {
    const div = document.createElement("div");
    const roleClass = message.role === "user" ? "mv-bubble-user"
      : message.role === "aivan" ? "mv-bubble-aivan" : "mv-bubble-system";
    div.className = "mv-bubble " + roleClass;
    if (message.type === "file" || message.type === "image") {
      div.innerHTML = '<span class="mv-file-card"></span>';
      div.querySelector("span").textContent = message.content;
    } else {
      div.textContent = message.content;
    }
    const meta = document.createElement("span");
    meta.className = "mv-bubble-meta";
    meta.textContent = message.type + " · " + (message.createdAt || "").slice(0, 19).replace("T", " ");
    div.appendChild(meta);
    return div;
  }

  function riskNoteHtml(draft) {
    if (!draft.riskNotes || !draft.riskNotes.length) return "";
    const cls = draft.riskLevel === "high" ? "mv-risk-high" : "mv-risk-medium";
    return '<div class="mv-risk-note ' + cls + '">⚠ ' + t("draft.risk_label", "Risk")
      + " (" + draft.riskLevel + "): " + draft.riskNotes.join("; ") + "</div>";
  }

  function draftCard(draft) {
    const card = document.createElement("div");
    card.className = "mv-draft-card";
    card.dataset.draftId = draft.id;
    const terminal = ["email_sent", "manually_sent", "rejected"].includes(draft.status);
    card.innerHTML =
      '<div class="mv-draft-head">' +
        '<span class="mv-chip">channel: ' + draft.channel + "</span>" +
        (draft.recipient ? '<span class="mv-chip">to: ' + draft.recipient + "</span>" : "") +
        '<span class="mv-chip mv-chip-status-' + draft.status + '">' + draft.status + "</span>" +
      "</div>" +
      riskNoteHtml(draft) +
      '<div class="mv-draft-body"></div>' +
      '<div class="mv-draft-actions">' +
        '<button class="mv-act-copy"></button>' +
        '<button class="mv-act-email"></button>' +
        '<button class="mv-act-sent"></button>' +
        '<button class="mv-act-reject"></button>' +
      "</div>";
    card.querySelector(".mv-draft-body").textContent = draft.body;

    const labels = [
      [".mv-act-copy", t("draft.copy", "Copy"), t("draft.copy_tooltip", "Copy for manual paste")],
      [".mv-act-email", "✉️ " + t("draft.email", "Email"), t("draft.email_tooltip", "Send by Email")],
      [".mv-act-sent", "✅ " + t("draft.mark_sent", "Sent"), t("draft.mark_sent_tooltip", "Mark as manually sent")],
      [".mv-act-reject", "❌ " + t("draft.reject", "Reject"), t("draft.reject_tooltip", "Reject draft")],
    ];
    labels.forEach(([sel, label, tooltip]) => {
      const btn = card.querySelector(sel);
      btn.textContent = label;
      btn.title = tooltip;
    });

    if (terminal) {
      card.querySelectorAll(".mv-draft-actions button").forEach((b) => { b.disabled = true; });
    }
    const emailBtn = card.querySelector(".mv-act-email");
    if (!terminal && !realEmailReady()) {
      emailBtn.disabled = true;
      emailBtn.title = emailReadinessMessage();
    }
    card.querySelector(".mv-act-copy").addEventListener("click", () => copyDraft(draft));
    emailBtn.addEventListener("click", () => openEmailModal(draft));
    card.querySelector(".mv-act-sent").addEventListener("click", () => draftAction(draft.id, "mark-sent"));
    card.querySelector(".mv-act-reject").addEventListener("click", () => draftAction(draft.id, "reject"));
    return card;
  }

  function render(state) {
    lastState = state;
    stream.innerHTML = "";
    (state.messages || []).forEach((m) => stream.appendChild(bubble(m)));
    stream.scrollTop = stream.scrollHeight;

    draftCards.innerHTML = "";
    const drafts = state.outboundDrafts || [];
    if (!drafts.length) {
      const empty = document.createElement("div");
      empty.className = "mv-review-empty";
      empty.dataset.i18n = "work.review_empty";
      empty.textContent = t("work.review_empty",
        "AIVAN-generated outbound drafts will appear here for your review. Every outbound message requires human confirmation.");
      draftCards.appendChild(empty);
    } else {
      drafts.slice().reverse().forEach((d) => draftCards.appendChild(draftCard(d)));
    }
  }

  // Re-render translated card labels when the language changes.
  document.addEventListener("myaivan:lang", () => { if (lastState) render(lastState); });

  // ── resizable work areas ──────────────────────────────────────────────────

  function px(n) { return Math.max(0, Math.round(n)) + "px"; }

  function currentLayout() {
    return {
      stream: stream.getBoundingClientRect().height,
      review: review.getBoundingClientRect().height,
      inputbar: inputbar.getBoundingClientRect().height,
    };
  }

  function applyLayout(layout) {
    if (!layout) return;
    if (layout.stream) stream.style.flex = "0 0 " + px(layout.stream);
    if (layout.review) review.style.flex = "0 0 " + px(layout.review);
    if (layout.inputbar) inputbar.style.flex = "0 0 " + px(layout.inputbar);
  }

  function saveLayout() {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(currentLayout())); } catch (e) { /* ignore */ }
  }

  function restoreLayout() {
    try {
      const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "null");
      if (saved && saved.stream && saved.review && saved.inputbar) applyLayout(saved);
    } catch (e) { /* ignore */ }
  }

  function initResizer(handleId, upperEl, lowerEl, upperMin, lowerMin) {
    const handle = document.getElementById(handleId);
    if (!handle || !upperEl || !lowerEl) return;
    handle.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      handle.setPointerCapture(ev.pointerId);
      document.body.classList.add("mv-resizing");
      const startY = ev.clientY;
      const upperStart = upperEl.getBoundingClientRect().height;
      const lowerStart = lowerEl.getBoundingClientRect().height;
      const total = upperStart + lowerStart;

      function onMove(moveEv) {
        const delta = moveEv.clientY - startY;
        let upperNext = Math.max(upperMin, upperStart + delta);
        let lowerNext = Math.max(lowerMin, total - upperNext);
        if (lowerNext === lowerMin) upperNext = total - lowerMin;
        upperEl.style.flex = "0 0 " + px(upperNext);
        lowerEl.style.flex = "0 0 " + px(lowerNext);
      }

      function onUp(upEv) {
        handle.releasePointerCapture(upEv.pointerId);
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
        document.body.classList.remove("mv-resizing");
        saveLayout();
      }

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });
  }

  restoreLayout();
  initResizer("stream-review-resizer", stream, review, 120, 112);
  initResizer("review-input-resizer", review, inputbar, 112, 168);

  // ── case bootstrap ─────────────────────────────────────────────────────────

  async function ensureCase() {
    const saved = localStorage.getItem(CASE_KEY);
    if (saved) {
      try {
        const state = await api("/cases/" + saved);
        activeCaseId = saved;
        render(state);
        restoreLastBackupIntoInput();
        return;
      } catch (e) { /* stale id → create a new case */ }
    }
    const state = await api("/cases", { method: "POST", body: JSON.stringify({}) });
    activeCaseId = state.case.id;
    localStorage.setItem(CASE_KEY, activeCaseId);
    render(state);
    restoreLastBackupIntoInput();
  }

  // ── actions ────────────────────────────────────────────────────────────────

  async function sendMessage(type) {
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    setStatus(t("status.processing", "AIVAN is processing…"));
    try {
      const state = await api("/cases/" + activeCaseId + "/messages", {
        method: "POST",
        body: JSON.stringify({ content: content, type: type || "text" }),
      });
      render(state);
      setStatus("");
    } catch (e) {
      setStatus(t("status.send_failed", "Send failed") + ": " + e.message);
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = (input.value ? input.value + "\n" : "") + text;
        input.focus();
        setStatus(t("status.pasted", "Clipboard content pasted into the input box."));
        return;
      }
      setStatus(t("status.clipboard_empty", "Clipboard is empty."));
    } catch (e) {
      setStatus(t("status.paste_fallback", "Please paste manually with Ctrl+V / Cmd+V."));
    }
  }

  async function upload(fileInput) {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setStatus(t("status.uploading", "Uploading…"));
    try {
      const resp = await fetch(API + "/cases/" + activeCaseId + "/uploads", {
        method: "POST",
        headers: authHeaders(),
        body: form,
      });
      if (resp.status === 401 || resp.status === 403) handleAuthFailure();
      const state = await resp.json();
      if (!resp.ok) throw new Error(state.detail || resp.status);
      render(state);
      setStatus("");
    } catch (e) {
      setStatus(t("status.upload_failed", "Upload failed") + ": " + e.message);
    } finally {
      fileInput.value = "";
    }
  }

  async function copyDraft(draft) {
    let copied = false;
    try {
      await navigator.clipboard.writeText(draft.body);
      copied = true;
    } catch (e) { /* clipboard blocked; body text remains selectable */ }
    try {
      const state = await api("/cases/" + activeCaseId + "/drafts/" + draft.id + "/copied", { method: "POST" });
      render(state);
    } catch (e) { /* audit failure should not block the user */ }
    setStatus(copied
      ? t("status.copied", "Copied — paste it into your IM tool, then click ✅.")
      : t("status.copy_blocked", "Clipboard blocked — select the draft text and copy manually."));
  }

  async function draftAction(draftId, action) {
    try {
      const state = await api("/cases/" + activeCaseId + "/drafts/" + draftId + "/" + action, { method: "POST" });
      render(state);
      setStatus(action === "mark-sent"
        ? t("status.marked_sent", "Recorded as manually sent.")
        : t("status.rejected", "Draft rejected — tell AIVAN how to revise it."));
    } catch (e) {
      setStatus(t("status.action_failed", "Action failed") + ": " + e.message);
    }
  }

  // ── email modal ────────────────────────────────────────────────────────────

  const modal = document.getElementById("email-modal");
  const modalNote = document.getElementById("email-modal-note");
  const recipientInput = document.getElementById("email-recipient");

  function openEmailModal(draft) {
    if (!realEmailReady()) {
      setStatus(emailReadinessMessage());
      return;
    }
    pendingEmailDraftId = draft.id;
    recipientInput.value = draft.recipient || "";
    modalNote.textContent = t("email.modal_real", "This will send a real email through aivan-openclaw.");
    modal.hidden = false;
  }

  async function confirmEmail() {
    const draftId = pendingEmailDraftId;
    modal.hidden = true;
    if (!draftId) return;
    setStatus(t("status.email_sending", "Sending email…"));
    try {
      const state = await api("/cases/" + activeCaseId + "/drafts/" + draftId + "/send-email", {
        method: "POST",
        body: JSON.stringify({
          recipient: recipientInput.value.trim(),
          emailApiKey: storedEmailApiKey(),
        }),
      });
      render(state);
      const r = state.emailResult || {};
      if (r.success) {
        setStatus(r.provider === "mock"
          ? t("status.email_mock", "Mock send recorded — no real email was delivered.")
          : r.provider === "smtp"
            ? t("status.email_smtp", "Email sent via SMTP.")
            : t("status.email_sent", "Email sent via aivan-openclaw."));
      } else {
        setStatus(t("status.email_failed", "Email failed") + ": " + (r.error || "unknown error"));
      }
    } catch (e) {
      setStatus(t("status.email_failed", "Email failed") + ": " + e.message);
    }
    pendingEmailDraftId = null;
  }

  // ── backup ─────────────────────────────────────────────────────────────────

  async function backup(options) {
    const opts = options || {};
    if (!activeCaseId) return;
    try {
      const resp = await fetch(API + "/cases/" + activeCaseId + "/backup.md", { headers: authHeaders() });
      if (resp.status === 401 || resp.status === 403) handleAuthFailure();
      if (!resp.ok) throw new Error(String(resp.status));
      const text = await resp.text();
      rememberBackup(text, opts.auto ? "scheduled backup" : "manual backup");
      const prefix = opts.auto ? "myaivan-autobackup-" : "aivan-case-";
      downloadText(prefix + activeCaseId + ".md", text);
      if (!opts.auto) setStatus(t("status.backup_done", "Backup exported."));
    } catch (e) {
      if (opts.auto) {
        backupFromLastState("scheduled backup fallback");
      } else {
        setStatus(t("status.backup_failed", "Backup failed") + ": " + e.message);
      }
    }
  }

  async function logout() {
    setStatus(t("status.logging_out", "Signing out…"));
    try {
      await fetch(API + "/logout", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
      });
    } catch (e) { /* redirect anyway; server cookie may already be gone */ }
    document.cookie = "myaivan_session=; Max-Age=0; path=/";
    window.location.href = "/myaivan/login";
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  const settingsToggle = document.getElementById("settings-toggle");
  const settingsMenu = document.getElementById("settings-menu");
  const settingsApiKey = document.getElementById("settings-api-key");
  const settingsEmailApiKey = document.getElementById("settings-email-api-key");
  const settingsEmailStatus = document.getElementById("settings-email-status");
  const settingsSaveKey = document.getElementById("settings-save-key");
  const settingsClearKey = document.getElementById("settings-clear-key");
  const settingsSaveEmailKey = document.getElementById("settings-save-email-key");
  const settingsClearEmailKey = document.getElementById("settings-clear-email-key");

  function setSettingsOpen(open) {
    settingsMenu.hidden = !open;
    settingsToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      settingsApiKey.value = storedApiKey();
      settingsEmailApiKey.value = storedEmailApiKey();
      updateEmailSettingsStatus();
      settingsApiKey.focus();
    }
  }

  function updateEmailSettingsStatus() {
    if (settingsEmailStatus) settingsEmailStatus.textContent = emailReadinessMessage();
  }

  settingsToggle.addEventListener("click", (ev) => {
    ev.stopPropagation();
    setSettingsOpen(settingsMenu.hidden);
  });
  settingsMenu.addEventListener("click", (ev) => ev.stopPropagation());
  document.addEventListener("click", () => setSettingsOpen(false));
  settingsSaveKey.addEventListener("click", () => {
    try { localStorage.setItem(API_KEY_KEY, settingsApiKey.value.trim()); } catch (e) { /* ignore */ }
    setStatus(t("status.api_key_saved", "API Key saved in this browser."));
    setSettingsOpen(false);
  });
  settingsClearKey.addEventListener("click", () => {
    try { localStorage.removeItem(API_KEY_KEY); } catch (e) { /* ignore */ }
    settingsApiKey.value = "";
    setStatus(t("status.api_key_cleared", "API Key cleared from this browser."));
    setSettingsOpen(false);
  });
  settingsSaveEmailKey.addEventListener("click", () => {
    try { localStorage.setItem(EMAIL_API_KEY_KEY, settingsEmailApiKey.value.trim()); } catch (e) { /* ignore */ }
    updateEmailSettingsStatus();
    if (lastState) render(lastState);
    setStatus(t("status.email_api_key_saved", "Email API Key saved in this browser."));
    setSettingsOpen(false);
  });
  settingsClearEmailKey.addEventListener("click", () => {
    try { localStorage.removeItem(EMAIL_API_KEY_KEY); } catch (e) { /* ignore */ }
    settingsEmailApiKey.value = "";
    updateEmailSettingsStatus();
    if (lastState) render(lastState);
    setStatus(t("status.email_api_key_cleared", "Email API Key cleared from this browser."));
    setSettingsOpen(false);
  });

  document.getElementById("send-btn").addEventListener("click", () => sendMessage("text"));
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendMessage("text"); }
  });
  document.getElementById("paste-btn").addEventListener("click", pasteFromClipboard);
  document.getElementById("file-input").addEventListener("change", (ev) => upload(ev.target));
  document.getElementById("image-input").addEventListener("change", (ev) => upload(ev.target));
  document.getElementById("voice-btn").addEventListener("click", () => {
    setStatus(t("status.voice_soon", "Voice input coming soon."));
  });
  document.getElementById("backup-btn").addEventListener("click", backup);
  document.getElementById("logout-btn").addEventListener("click", logout);
  document.getElementById("email-confirm").addEventListener("click", confirmEmail);
  document.getElementById("email-cancel").addEventListener("click", () => {
    modal.hidden = true;
    pendingEmailDraftId = null;
  });

  ensureCase().catch((e) => setStatus(t("status.init_failed", "Initialization failed") + ": " + e.message));
  setInterval(() => backup({ auto: true }), AUTO_BACKUP_INTERVAL_MS);
})();
