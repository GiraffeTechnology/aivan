'use strict';

window.myAivanAttachments = (() => {
  const types = new Set(['text/plain', 'image/png', 'image/jpeg']);
  const maxBytes = 10 * 1024 * 1024;
  let dispose = () => {};
  const base = caseId => `/api/workbench/cases/${encodeURIComponent(caseId)}/attachments`;
  const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');

  function contentPath(caseId, item) {
    if (typeof item.attachment_id !== 'string' || !item.attachment_id) throw Error('INVALID_ATTACHMENT');
    const expected = `${base(caseId)}/${encodeURIComponent(item.attachment_id)}/content`;
    if (item.download_path !== expected) throw Error('INVALID_DOWNLOAD_PATH');
    return expected;
  }

  async function fileBody(file) {
    if (!file || !types.has(file.type) || file.size < 1 || file.size > maxBytes) throw Error('INVALID_FILE');
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.byteLength !== file.size) throw Error('INVALID_FILE');
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return {file_name:file.name, content_type:file.type, content_base64:btoa(binary), sha256:await digest(bytes)};
  }

  function mount(root, caseId, api) {
    dispose();
    let alive = true;
    let retry = null;
    const urls = new Set();
    const controller = new AbortController();
    dispose = () => { alive = false; controller.abort(); urls.forEach(url => URL.revokeObjectURL(url)); urls.clear(); };
    const node = (tag, text) => { const element = document.createElement(tag); if (text) element.textContent = text; return element; };
    root.replaceChildren();
    root.append(node('h2', 'Files and images'));
    if (!caseId) { root.append(node('p', 'Save a complete inquiry and open its case before uploading.')); return; }
    const form = node('form');
    const label = node('label', 'Upload a TXT, PNG or JPEG file (maximum 10 MiB)');
    const input = node('input');
    input.type = 'file'; input.accept = '.txt,.png,.jpg,.jpeg,text/plain,image/png,image/jpeg'; input.required = true;
    label.append(input);
    const button = node('button', 'Upload to this case'); button.type = 'submit'; button.className = 'secondary';
    const status = node('p'); status.setAttribute('role', 'status');
    const cards = node('div');
    form.append(label, button); root.append(form, status, cards);

    async function preview(item, card, button) {
      button.disabled = true;
      try {
        const response = await fetch(contentPath(caseId, item), {credentials:'same-origin', redirect:'error', signal:controller.signal});
        if (!response.ok) throw Error('CONTENT_UNAVAILABLE');
        const mime = (response.headers.get('Content-Type') || '').split(';')[0].trim();
        if (!['image/png', 'image/jpeg'].includes(mime) || mime !== item.content_type) throw Error('INVALID_IMAGE');
        const blob = await response.blob();
        if (blob.size > maxBytes || blob.size !== item.size_bytes || await digest(await blob.arrayBuffer()) !== item.sha256) throw Error('INVALID_IMAGE');
        if (!alive) return;
        const url = URL.createObjectURL(blob); urls.add(url);
        const image = node('img'); image.src = url; image.alt = 'Stored image preview; content has not been parsed.'; image.className = 'attachment-preview';
        image.addEventListener('error', () => {
          URL.revokeObjectURL(url); urls.delete(url);
          if (alive) { card.append(node('p', 'The browser could not display this image. Use the saved-file download instead.')); button.disabled = false; }
        });
        card.append(image);
      } catch {
        if (alive) { card.append(node('p', 'Image preview unavailable. No extracted content is claimed.')); button.disabled = false; }
      }
    }

    async function refresh() {
      const result = await api(base(caseId));
      if (!alive) return;
      if (result.readback_verified !== true || !Array.isArray(result.items)) throw Error('READBACK_UNVERIFIED');
      urls.forEach(url => URL.revokeObjectURL(url)); urls.clear(); cards.replaceChildren();
      for (const item of result.items) {
        const path = contentPath(caseId, item);
        const card = node('article'); card.className = 'draft-card';
        card.append(node('strong', item.file_name), node('p', `Stored and read back: ${item.content_type} · ${item.size_bytes} bytes`));
        const link = node('a', 'Download saved file'); link.href = path; link.download = ''; card.append(link);
        if (['image/png', 'image/jpeg'].includes(item.content_type)) {
          card.append(node('p', 'Image stored, not parsed. No OCR or summary is available.'));
          const show = node('button', 'Preview image'); show.type = 'button';
          show.addEventListener('click', () => preview(item, card, show)); card.append(show);
        }
        cards.append(card);
      }
      if (!result.items.length) cards.append(node('p', 'No saved attachments.'));
    }

    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (button.disabled) return;
      button.disabled = true; input.disabled = true;
      status.textContent = 'Uploading and verifying saved content…';
      let persisted = false;
      try {
        const body = await fileBody(input.files[0]);
        const fingerprint = JSON.stringify(body);
        if (!retry || retry.fingerprint !== fingerprint) retry = {fingerprint, key:`attachment-${crypto.randomUUID()}`};
        const result = await api(base(caseId), {method:'POST', headers:{'Idempotency-Key':retry.key}, body:JSON.stringify(body)});
        if (result.readback_verified !== true) throw Error('READBACK_UNVERIFIED');
        contentPath(caseId, result);
        persisted = true; retry = null;
        if (!alive) return;
        input.value = '';
        status.textContent = result.processing_status === 'canonical_text_available' && result.canonical_language === 'en'
          ? 'Saved and read back. Canonical English text is available.'
          : 'Saved and read back. No parsed content or summary is claimed.';
        if (result.processing_status === 'canonical_text_available' && result.canonical_language === 'en' && typeof result.canonical_text === 'string') {
          status.append(node('pre', result.canonical_text));
        }
        await refresh();
      } catch (error) {
        if (alive) status.textContent = persisted ? 'File saved, but the attachment list could not be refreshed. Reopen the case to verify.'
          : error.message === 'INVALID_FILE' ? 'Choose a non-empty TXT, PNG or JPEG file no larger than 10 MiB.'
          : error.status === 409 ? 'Upload conflict: ensure the case is saved and review its current state before retrying.'
          : [401, 403].includes(error.status) ? 'Upload not authorized. Check your session and case permissions.'
          : 'Upload could not be verified. Reopen the case to check; retrying the same file uses the same request key in this view.';
      } finally { if (alive) { button.disabled = false; input.disabled = false; } }
    });
    refresh().catch(() => { if (alive) status.textContent = 'Saved attachments could not be loaded. No empty-history claim is made.'; });
  }
  return {mount, dispose:() => dispose(), fileBody, contentPath};
})();
