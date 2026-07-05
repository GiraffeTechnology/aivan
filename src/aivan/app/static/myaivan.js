/* myaivan conversation page controller.
 *
 * Product boundaries enforced here:
 *  - No direct IM sending: IM drafts only offer Copy → user pastes manually → ✅.
 *  - ✉️ sends email ONLY through the backend adapter (aivan-openclaw or mock),
 *    always behind an explicit confirmation modal.
 *  - Mock email results are labeled as mock, never as real delivery.
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

  function setStatus(text) { statusLine.textContent = text || ""; }

  async function api(path, options) {
    const resp = await fetch(API + path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options));
    const data = await resp.json().catch(() => ({}));
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
    return '<div class="mv-risk-note ' + cls + '">⚠ 风险提示 Risk (' + draft.riskLevel + "): "
      + draft.riskNotes.join("; ") + "</div>";
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
        '<button class="mv-act-copy" title="Copy for manual paste · 复制，用于手动粘贴">复制 Copy</button>' +
        '<button class="mv-act-email" title="Send by Email · 通过邮件外发">✉️ Email</button>' +
        '<button class="mv-act-sent" title="Mark as manually sent · 已粘贴并发送">✅ 已发送</button>' +
        '<button class="mv-act-reject" title="Reject draft · 审核不通过">❌ 不通过</button>' +
      "</div>";
    card.querySelector(".mv-draft-body").textContent = draft.body;
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
    stream.innerHTML = "";
    (state.messages || []).forEach((m) => stream.appendChild(bubble(m)));
    stream.scrollTop = stream.scrollHeight;

    draftCards.innerHTML = "";
    const drafts = state.outboundDrafts || [];
    if (!drafts.length) {
      draftCards.innerHTML = '<div class="mv-review-empty">AIVAN-generated outbound drafts will appear here for your review. 生成的外发草稿会出现在这里，需人工确认后再外发。</div>';
    } else {
      drafts.slice().reverse().forEach((d) => draftCards.appendChild(draftCard(d)));
    }
  }

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
    setStatus("AIVAN 正在处理… processing…");
    try {
      const state = await api("/cases/" + activeCaseId + "/messages", {
        method: "POST",
        body: JSON.stringify({ content: content, type: type || "text" }),
      });
      render(state);
      setStatus("");
    } catch (e) {
      setStatus("发送失败 Send failed: " + e.message);
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        input.value = (input.value ? input.value + "\n" : "") + text;
        input.focus();
        setStatus("剪贴板内容已粘贴到输入框。Clipboard content pasted into the input box.");
        return;
      }
      setStatus("剪贴板为空。Clipboard is empty.");
    } catch (e) {
      setStatus("浏览器未允许读取剪贴板，请使用 Ctrl+V / Cmd+V 手动粘贴。Please paste manually with Ctrl+V / Cmd+V.");
    }
  }

  async function upload(fileInput) {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setStatus("上传中… uploading…");
    try {
      const resp = await fetch(API + "/cases/" + activeCaseId + "/uploads", { method: "POST", body: form });
      const state = await resp.json();
      if (!resp.ok) throw new Error(state.detail || resp.status);
      render(state);
      setStatus("");
    } catch (e) {
      setStatus("上传失败 Upload failed: " + e.message);
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
      ? "已复制，请粘贴到微信 / WhatsApp / LINE / 旺旺后回来点 ✅。Copied — paste it into your IM tool, then click ✅."
      : "浏览器未允许写剪贴板，请手动选择草稿文本复制。Clipboard blocked — select the draft text and copy manually.");
  }

  async function draftAction(draftId, action) {
    try {
      const state = await api("/cases/" + activeCaseId + "/drafts/" + draftId + "/" + action, { method: "POST" });
      render(state);
      setStatus(action === "mark-sent"
        ? "已记录为人工外发。Recorded as manually sent."
        : "草稿已拒绝，请告诉 AIVAN 如何修改。Draft rejected — tell AIVAN how to revise it.");
    } catch (e) {
      setStatus("操作失败 Action failed: " + e.message);
    }
  }

  // ── email modal ────────────────────────────────────────────────────────────

  const modal = document.getElementById("email-modal");
  const modalNote = document.getElementById("email-modal-note");
  const recipientInput = document.getElementById("email-recipient");

  function openEmailModal(draft) {
    if (emailStatus === "not_configured") {
      setStatus("邮件外发尚未配置，请复制草稿后手动发送。Email sending is not configured. Please copy the draft manually.");
      return;
    }
    pendingEmailDraftId = draft.id;
    recipientInput.value = draft.recipient || "";
    modalNote.textContent = emailStatus === "mock"
      ? "当前为 MOCK 演示模式：不会真正发出邮件。Mock mode: no real email will be delivered."
      : "将通过 aivan-openclaw 真实外发邮件，请确认收件人与内容。This will send a real email through aivan-openclaw.";
    modal.hidden = false;
  }

  async function confirmEmail() {
    const draftId = pendingEmailDraftId;
    modal.hidden = true;
    if (!draftId) return;
    setStatus("正在外发邮件… sending email…");
    try {
      const state = await api("/cases/" + activeCaseId + "/drafts/" + draftId + "/send-email", {
        method: "POST",
        body: JSON.stringify({ recipient: recipientInput.value.trim() }),
      });
      render(state);
      const r = state.emailResult || {};
      if (r.success) {
        setStatus(r.provider === "mock"
          ? "MOCK 模式外发成功（未真实发送）。Mock send recorded — no real email was delivered."
          : "邮件已通过 aivan-openclaw 外发。Email sent via aivan-openclaw.");
      } else {
        setStatus("邮件外发失败 Email failed: " + (r.error || "unknown error"));
      }
    } catch (e) {
      setStatus("邮件外发失败 Email failed: " + e.message);
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
      setStatus("备份已导出 Backup exported.");
    } catch (e) {
      setStatus("备份失败 Backup failed: " + e.message);
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
    setStatus("语音输入即将上线。Voice input coming soon.");
  });
  document.getElementById("backup-btn").addEventListener("click", backup);
  document.getElementById("email-confirm").addEventListener("click", confirmEmail);
  document.getElementById("email-cancel").addEventListener("click", () => {
    modal.hidden = true;
    pendingEmailDraftId = null;
  });

  ensureCase().catch((e) => setStatus("初始化失败 Init failed: " + e.message));
})();
