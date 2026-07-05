/* myaivan conversation page controller.
 *
 * Product boundaries enforced here:
 *  - No direct IM sending: IM drafts only offer Copy → user pastes manually → ✅.
 *  - ✉️ sends email ONLY through the backend adapter (aivan-openclaw or mock),
 *    always behind an explicit confirmation modal.
 *  - Mock email results are labeled as mock, never as real delivery.
 *
 * All user-visible strings resolve through MyaivanI18n.t() (English canonical,
 * other languages served by /api/myaivan/i18n via giraffe-language-skill).
 */
(function () {
  "use strict";

  const API = "/api/myaivan";
  const CASE_KEY = "myaivan.activeCaseId";
  const emailStatus = document.body.dataset.emailStatus || "not_configured";

  const stream = document.getElementById("conversation-stream");
  const draftCards = document.getElementById("draft-cards");
  const input = document.getElementById("message-input");
  const statusLine = document.getElementById("status-line");

  let activeCaseId = null;
  let pendingEmailDraftId = null;
  let lastState = null;

  function t(key, fallback) {
    return (window.MyaivanI18n && window.MyaivanI18n.t(key, fallback)) || fallback || key;
  }

  function setStatus(text) { statusLine.textContent = text || ""; }

  async function api(path, options) {
    const resp = await fetch(API + path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options));
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 401) {
      window.location.href = "/myaivan/login";
      throw new Error("authentication required");
    }
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
    card.querySelector(".mv-act-copy").addEventListener("click", () => copyDraft(draft));
    card.querySelector(".mv-act-email").addEventListener("click", () => openEmailModal(draft));
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

  // ── case bootstrap ─────────────────────────────────────────────────────────

  async function ensureCase() {
    const saved = localStorage.getItem(CASE_KEY);
    if (saved) {
      try {
        const state = await api("/cases/" + saved);
        activeCaseId = saved;
        render(state);
        return;
      } catch (e) { /* stale id → create a new case */ }
    }
    const state = await api("/cases", { method: "POST", body: JSON.stringify({}) });
    activeCaseId = state.case.id;
    localStorage.setItem(CASE_KEY, activeCaseId);
    render(state);
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
      const resp = await fetch(API + "/cases/" + activeCaseId + "/uploads", { method: "POST", body: form });
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
    if (emailStatus === "not_configured") {
      setStatus(t("status.email_not_configured",
        "Email sending is not configured. Please copy the draft manually."));
      return;
    }
    pendingEmailDraftId = draft.id;
    recipientInput.value = draft.recipient || "";
    modalNote.textContent = emailStatus === "mock"
      ? t("email.modal_mock", "Mock mode: no real email will be delivered.")
      : t("email.modal_real", "This will send a real email through aivan-openclaw.");
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
        body: JSON.stringify({ recipient: recipientInput.value.trim() }),
      });
      render(state);
      const r = state.emailResult || {};
      if (r.success) {
        setStatus(r.provider === "mock"
          ? t("status.email_mock", "Mock send recorded — no real email was delivered.")
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

  async function backup() {
    try {
      const resp = await fetch(API + "/cases/" + activeCaseId + "/backup.md");
      if (!resp.ok) throw new Error(String(resp.status));
      const text = await resp.text();
      const blob = new Blob([text], { type: "text/markdown" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "aivan-case-" + activeCaseId + ".md";
      a.click();
      URL.revokeObjectURL(a.href);
      setStatus(t("status.backup_done", "Backup exported."));
    } catch (e) {
      setStatus(t("status.backup_failed", "Backup failed") + ": " + e.message);
    }
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

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
  document.getElementById("email-confirm").addEventListener("click", confirmEmail);
  document.getElementById("email-cancel").addEventListener("click", () => {
    modal.hidden = true;
    pendingEmailDraftId = null;
  });

  ensureCase().catch((e) => setStatus(t("status.init_failed", "Initialization failed") + ": " + e.message));
})();
