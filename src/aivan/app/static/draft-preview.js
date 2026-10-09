/* Transient commercial previews. No rendered text is written to browser storage. */
(() => {
  let active = null;
  let generation = 0;
  const safeHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const newKey = () => `preview-copy-${crypto.randomUUID()}`;

  async function open({draftId, api, onApproved}) {
    if (active) active.close();
    const current = ++generation;
    const dialog = document.createElement('dialog');
    dialog.className = 'commercial-preview';
    dialog.setAttribute('aria-label', 'Review the final commercial message');
    dialog.innerHTML = `<h2>Review the final message</h2>
      <p>Choose the recipient language, then inspect the exact sender, recipient and body before approving.</p>
      <label>Target language code <input name="language" value="en" maxlength="3" pattern="[a-z]{2,3}" autocomplete="off"></label>
      <label><input name="manual" type="checkbox"> I will copy and send this message myself</label>
      <button type="button" data-preview="render">Generate preview</button>
      <p data-preview="identity"></p>
      <label>Final message <textarea data-preview="body" rows="10" readonly></textarea></label>
      <p data-preview="status" role="status" aria-live="polite"></p>
      <div class="row-actions"><button type="button" data-preview="approve" disabled>Approve this exact message</button>
      <button type="button" data-preview="copy" disabled>Copy approved message</button>
      <button type="button" data-preview="close">Close</button></div>`;
    document.body.append(dialog);
    const find = selector => dialog.querySelector(selector);
    const language = find('[name="language"]');
    const manual = find('[name="manual"]');
    const renderButton = find('[data-preview="render"]');
    const approveButton = find('[data-preview="approve"]');
    const copyButton = find('[data-preview="copy"]');
    const body = find('[data-preview="body"]');
    const status = find('[data-preview="status"]');
    let proof = null;
    let busy = false;
    let copyKey = null;
    const isCurrent = () => current === generation && active === dialog;
    function resetProof() {
      proof = null; copyKey = null;
      body.value = ''; approveButton.disabled = true; copyButton.disabled = true;
    }
    function working(value) {
      busy = value; renderButton.disabled = value; language.disabled = value;
      if (!value && proof && proof.channel !== 'email' && proof.channel !== 'smtp') manual.disabled = true;
      else manual.disabled = value;
    }
    async function render() {
      if (busy) return;
      resetProof(); working(true); status.textContent = 'Generating a preview. Nothing has been sent.';
      try {
        const value = await api(`/api/drafts/${encodeURIComponent(draftId)}/preview`, {
          method: 'POST', body: JSON.stringify({target_language: language.value.trim().toLowerCase(), manual_delivery: manual.checked}),
        });
        if (!isCurrent()) return;
        if (!value.preview_id || value.approval_required !== true || !safeHash(value.rendered_sha256)
            || !safeHash(value.source_sha256) || typeof value.message_text !== 'string' || !value.message_text) {
          throw Error('Invalid preview response');
        }
        proof = value; body.value = value.message_text; manual.checked = value.manual_delivery === true;
        find('[data-preview="identity"]').textContent = `From: ${value.sender} | To: ${value.recipient} | Channel: ${value.channel} | Language: ${value.target_language}`;
        status.textContent = value.manual_delivery
          ? 'Manual delivery. Approval does not send this message. Copy it after approving, then confirm your receipt in the relay queue.'
          : 'Approval will send this exact message through the configured email channel.';
        approveButton.disabled = false;
      } catch (_) {
        if (isCurrent()) { resetProof(); status.textContent = 'A verified preview is unavailable. Nothing was sent. Retry after translation or configuration is available.'; }
      } finally { if (isCurrent()) working(false); }
    }
    language.addEventListener('input', resetProof);
    manual.addEventListener('change', resetProof);
    renderButton.addEventListener('click', render);
    approveButton.addEventListener('click', async () => {
      if (busy || !proof) return;
      const approvedProof = proof;
      working(true); approveButton.disabled = true; copyButton.disabled = true;
      status.textContent = 'Submitting your approval for the displayed message.';
      let approvedForCopy = false;
      try {
        const result = await api(`/api/drafts/${encodeURIComponent(draftId)}/approve`, {
          method: 'POST', body: JSON.stringify({preview_id: approvedProof.preview_id}),
        });
        if (!isCurrent()) return;
        if (result.relay_required === true && result.status === 'approved_pending_send') {
          status.textContent = 'Approved for manual delivery. Copy and send it yourself, then record the receipt in the relay queue.';
          approvedForCopy = true;
        } else if (result.sent === true && result.status === 'sent') {
          status.textContent = 'The approved message was sent and a delivery result was recorded.';
        } else {
          resetProof(); status.textContent = 'No delivery is confirmed. Generate a fresh preview before trying again.';
        }
        if (onApproved) { try { await onApproved(result); } catch (_) { /* Saved delivery state remains authoritative. */ } }
      } catch (_) {
        if (isCurrent()) { resetProof(); status.textContent = 'Approval or delivery was not confirmed. Reopen the draft and review its saved state before retrying.'; }
      } finally {
        if (isCurrent()) {
          working(false);
          copyButton.disabled = !approvedForCopy || proof !== approvedProof;
        }
      }
    });
    copyButton.addEventListener('click', async () => {
      if (busy || !proof || copyButton.disabled || !isCurrent() || !dialog.open) return;
      const copied = proof;
      const isCurrentCopy = () => isCurrent() && dialog.open && proof === copied;
      working(true); copyButton.disabled = true;
      let clipboardDone = false;
      try {
        const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(copied.message_text));
        if (!isCurrentCopy()) return;
        const actual = Array.from(new Uint8Array(hash), v => v.toString(16).padStart(2, '0')).join('');
        if (actual !== copied.rendered_sha256) throw Error('Preview changed');
        await navigator.clipboard.writeText(copied.message_text); clipboardDone = true;
        // An invoked clipboard write cannot be cancelled; do not start a stale audit after it settles.
        if (!isCurrentCopy()) return;
        copyKey ||= newKey();
        const result = await api(`/api/workbench/cases/${encodeURIComponent(copied.case_id)}/drafts/${encodeURIComponent(draftId)}/copy`, {
          method: 'POST', headers: {'Idempotency-Key': copyKey},
          body: JSON.stringify({content_sha256: copied.rendered_sha256, preview_id: copied.preview_id}),
        });
        if (!isCurrentCopy()) return;
        if (result.status !== 'copied' || result.delivery_claim !== false) throw Error('Copy receipt unavailable');
        copyKey = null; status.textContent = 'Copied and recorded. You still need to send it yourself; no delivery is claimed.';
      } catch (_) {
        if (isCurrentCopy()) {
          status.textContent = clipboardDone ? 'Copied, but the copy audit was not confirmed. No delivery is claimed.'
            : 'Automatic copying is unavailable. Select this approved text and copy it manually. No copy or delivery is claimed.';
          body.focus(); body.select();
        }
      } finally { if (isCurrent() && dialog.open) { working(false); copyButton.disabled = proof !== copied; } }
    });
    dialog.addEventListener('close', () => {
      resetProof(); find('[data-preview="identity"]').textContent = ''; status.textContent = '';
      if (active === dialog) { active = null; generation++; }
      dialog.remove();
    });
    find('[data-preview="close"]').addEventListener('click', () => dialog.close());
    active = dialog; dialog.showModal(); await render();
  }
  window.myAivanDraftPreview = {open};
})();
