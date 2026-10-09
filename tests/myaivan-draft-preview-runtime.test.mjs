import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto, createHash} from 'node:crypto';
const source = fs.readFileSync(new URL('../src/aivan/app/static/draft-preview.js', import.meta.url), 'utf8');
class Node {
  constructor() { this.events = {}; this.children = new Map(); this.disabled = false; this.value = ''; this.checked = false; }
  set innerHTML(value) { this.markup = value; }
  querySelector(key) {
    if (!this.children.has(key)) { const node = new Node(); if (key === '[name="language"]') node.value = 'en'; this.children.set(key, node); }
    return this.children.get(key);
  }
  setAttribute() {}
  addEventListener(type, fn) { this.events[type] = fn; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.(); }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  async click() { if (!this.disabled) return this.events.click?.(); }
}
const calls = [];
let dialog, clipboardFails = false, clipboard = '', clipboardCalls = 0, heldApproval = null, pendingRender = null;
let digestCalls = 0, pendingDigest = null, pendingClipboard = null, pendingCopy = null, copyFails = false;
const french = '\u0042\u006f\u006e\u006a\u006f\u0075\u0072\u002c\u0020\u0076\u006f\u0069\u0063\u0069\u0020\u0076\u006f\u0074\u0072\u0065\u0020\u0064\u0065\u0076\u0069\u0073\u002e';
function proof(language, manual, draftId = 'draft-1') {
  const second = draftId === 'draft-2';
  const message = language === 'en' ? (second ? 'Please review the second quotation.' : 'Please review this quotation.') : french;
  return {preview_id: 'render_' + (second ? 'c' : 'a').repeat(32), draft_id: draftId, case_id: second ? 'case-2' : 'case-1',
    target_language: language, manual_delivery: manual, approval_required: true,
    channel: 'email', sender: 'sender@example.invalid', recipient: 'buyer@example.invalid',
    source_sha256: 'b'.repeat(64), rendered_sha256: createHash('sha256').update(message).digest('hex'), message_text: message};
}
const api = async (path, options) => {
  const body = JSON.parse(options.body); calls.push({path, body, headers: options.headers});
  if (path.endsWith('/preview')) {
    if (pendingRender) return pendingRender;
    return proof(body.target_language, body.manual_delivery, decodeURIComponent(path.split('/')[3]));
  }
  if (path.endsWith('/approve')) return heldApproval;
  if (path.endsWith('/copy')) {
    if (copyFails) throw Error('Audit unavailable');
    if (pendingCopy) { pendingCopy.started.resolve(); return pendingCopy.promise; }
    return {status: 'copied', delivery_claim: false};
  }
  throw Error('Unexpected endpoint');
};
const window = {};
const context = vm.createContext({window, crypto: {
  randomUUID: () => webcrypto.randomUUID(),
  subtle: {digest: async (...args) => {
    digestCalls++;
    if (pendingDigest) { const held = pendingDigest; held.started.resolve(); await held.promise; }
    return webcrypto.subtle.digest(...args);
  }},
}, TextEncoder, Uint8Array,
  // Unit-only clipboard double. Browser acceptance must use the browser's real clipboard policy.
  navigator: {clipboard: {writeText: async value => {
    clipboardCalls++;
    if (pendingClipboard) { const held = pendingClipboard; held.started.resolve(); await held.promise; }
    if (clipboardFails) throw Error('denied');
    clipboard = value;
  }}},
  document: {createElement: () => new Node(), body: {append: node => { dialog = node; }}},
});
vm.runInContext(source, context);
await window.myAivanDraftPreview.open({draftId: 'draft-1', api});
const find = selector => dialog.querySelector(selector);
const language = find('[name="language"]');
language.value = 'fr'; language.events.input();
assert.equal(find('[data-preview="approve"]').disabled, true, 'A language change must remove approval readiness');
find('[name="manual"]').checked = true;
await find('[data-preview="render"]').click();
assert.equal(find('[data-preview="body"]').value, french);
let release;
heldApproval = new Promise(resolve => { release = resolve; });
const first = find('[data-preview="approve"]').click();
const duplicate = find('[data-preview="approve"]').click();
assert.equal(calls.filter(x => x.path.endsWith('/approve')).length, 1, 'Repeated approval clicks must submit only once');
release({relay_required: true, sent: false, status: 'approved_pending_send'});
await Promise.all([first, duplicate]);
clipboardFails = true;
const beforeCopy = calls.length;
await find('[data-preview="copy"]').click();
assert.equal(calls.length, beforeCopy, 'Denied clipboard access cannot record a successful copy');
clipboardFails = false;
await find('[data-preview="copy"]').click();
assert.equal(clipboard, french);
assert.deepEqual(Object.keys(calls.at(-1).body).sort(), ['content_sha256', 'preview_id']);
assert.ok(!JSON.stringify(calls).includes(french), 'No localized body may be submitted to an approval/copy persistence API');
const old = dialog;
old.close();
assert.equal(old.querySelector('[data-preview="body"]').value, '', 'Closing removes transient translated text');
let deliver;
pendingRender = new Promise(resolve => { deliver = resolve; });
const opening = window.myAivanDraftPreview.open({draftId: 'draft-1', api});
const abandoned = dialog;
abandoned.close();
deliver(proof('fr', true));
await opening;
assert.equal(abandoned.querySelector('[data-preview="body"]').value, '');
assert.equal(abandoned.querySelector('[data-preview="approve"]').disabled, true);
pendingRender = null;

function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return {promise, resolve, reject};
}
async function openManual(onApproved, draftId = 'draft-1') {
  await window.myAivanDraftPreview.open({draftId, api, onApproved});
  find('[name="manual"]').checked = true;
  await find('[data-preview="render"]').click();
}
const manualApproval = {relay_required: true, sent: false, status: 'approved_pending_send'};
heldApproval = manualApproval;
const callbackStarted = deferred();
const callbackFinished = deferred();
await openManual(async () => { callbackStarted.resolve(); await callbackFinished.promise; });
const approvalsBeforeCallback = calls.filter(x => x.path.endsWith('/approve')).length;
const copiesBeforeCallback = calls.filter(x => x.path.endsWith('/copy')).length;
const clipboardBeforeCallback = clipboardCalls;
const approving = find('[data-preview="approve"]').click();
await callbackStarted.promise;
const manualCopy = find('[data-preview="copy"]');
assert.equal(manualCopy.disabled, true, 'Copy must stay disabled while the approval callback keeps the handler busy');
await manualCopy.click();
await find('[data-preview="approve"]').click();
assert.equal(clipboardCalls, clipboardBeforeCallback, 'An immediate copy attempt while approval is busy must not touch the clipboard');
assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, copiesBeforeCallback, 'Busy approval must not record a copy');
assert.equal(calls.filter(x => x.path.endsWith('/approve')).length, approvalsBeforeCallback + 1, 'Repeated approval while its callback is pending must not submit again');
callbackFinished.resolve();
await approving;
assert.equal(manualCopy.disabled, false, 'Copy becomes actionable only after the approval callback settles');
const retryCopy = manualCopy.click();
const duplicateCopy = manualCopy.click();
await Promise.all([retryCopy, duplicateCopy]);
assert.equal(clipboardCalls, clipboardBeforeCallback + 1, 'A real retry copies once despite a repeated click');
assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, copiesBeforeCallback + 1, 'A real retry records exactly one copy');
assert.match(find('[data-preview="status"]').textContent, /^Copied and recorded\./);

const staleCallbackStarted = deferred();
const staleCallbackFinished = deferred();
await openManual(async () => { staleCallbackStarted.resolve(); await staleCallbackFinished.promise; });
const staleDialog = dialog;
const staleApproval = find('[data-preview="approve"]').click();
await staleCallbackStarted.promise;
staleDialog.close();
assert.equal(staleDialog.querySelector('[data-preview="body"]').value, '', 'Closing during the callback clears the approved text');
assert.equal(staleDialog.querySelector('[data-preview="copy"]').disabled, true);

heldApproval = {relay_required: false, sent: true, status: 'sent'};
const emailCallbackStarted = deferred();
const emailCallbackFinished = deferred();
await window.myAivanDraftPreview.open({draftId: 'draft-1', api,
  onApproved: async () => { emailCallbackStarted.resolve(); await emailCallbackFinished.promise; },
});
const emailDialog = dialog;
const emailApproval = find('[data-preview="approve"]').click();
await emailCallbackStarted.promise;
staleCallbackFinished.resolve();
await staleApproval;
assert.equal(staleDialog.querySelector('[data-preview="copy"]').disabled, true, 'A stale callback must not re-enable a closed dialog');
assert.equal(staleDialog.querySelector('[data-preview="body"]').value, '');
assert.equal(staleDialog.querySelector('[data-preview="status"]').textContent, '');
assert.equal(dialog, emailDialog);
assert.equal(find('[data-preview="render"]').disabled, true, 'A stale callback must not clear the newer approval busy state');
assert.equal(find('[data-preview="copy"]').disabled, true, 'Automatic email delivery must not enable manual copy during its callback');
emailCallbackFinished.resolve();
await emailApproval;
assert.equal(find('[data-preview="render"]').disabled, false);
assert.equal(find('[data-preview="copy"]').disabled, true, 'Automatic email delivery must not enable manual copy after its callback');
assert.match(find('[data-preview="status"]').textContent, /^The approved message was sent/);
const copiesBeforeEmailClick = calls.filter(x => x.path.endsWith('/copy')).length;
const clipboardBeforeEmailClick = clipboardCalls;
await find('[data-preview="copy"]').click();
assert.equal(clipboardCalls, clipboardBeforeEmailClick);
assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, copiesBeforeEmailClick);

heldApproval = manualApproval;
await openManual(async () => { throw Error('Refresh unavailable'); });
await find('[data-preview="approve"]').click();
assert.equal(find('[data-preview="copy"]').disabled, false, 'A failed refresh callback must preserve the saved manual approval');
await find('[data-preview="copy"]').click();
assert.match(find('[data-preview="status"]').textContent, /^Copied and recorded\./);
dialog.close();
// Deferred unit doubles expose each asynchronous boundary without granting browser permissions.
// An invoked native clipboard write cannot be cancelled. Once its dialog/proof is obsolete,
// suppress the later session-bound audit request, even if the physical copy eventually succeeds.
for (const stage of ['digest', 'clipboard']) {
  for (const interruption of ['close', 'new-draft', 'queued-close', 'proof-reset']) {
    await openManual();
    await find('[data-preview="approve"]').click();
    const previousDialog = dialog;
    const previousCopy = find('[data-preview="copy"]');
    const held = {...deferred(), started: deferred()};
    if (stage === 'digest') pendingDigest = held;
    else pendingClipboard = held;
    const beforeDigest = digestCalls;
    const beforeClipboard = clipboardCalls;
    const beforeAudits = calls.filter(x => x.path.endsWith('/copy')).length;
    const copying = previousCopy.click();
    await held.started.promise;
    await previousCopy.click();
    assert.equal(digestCalls, beforeDigest + 1, `${stage}/${interruption}: repeated click must not start a second digest`);
    assert.equal(clipboardCalls, beforeClipboard + (stage === 'clipboard' ? 1 : 0));
    if (interruption === 'close') previousDialog.close();
    if (interruption === 'queued-close') previousDialog.open = false; // Native close event can arrive later.
    if (interruption === 'proof-reset') previousDialog.querySelector('[name="language"]').events.input();
    if (interruption === 'close' || interruption === 'new-draft') {
      await openManual(undefined, 'draft-2');
      await find('[data-preview="approve"]').click();
    }
    const currentDialog = dialog;
    const currentStatus = find('[data-preview="status"]').textContent;
    const currentBody = find('[data-preview="body"]').value;
    pendingDigest = null; pendingClipboard = null;
    held.resolve();
    await copying;
    assert.equal(clipboardCalls, beforeClipboard + (stage === 'clipboard' ? 1 : 0),
      `${stage}/${interruption}: stale digest must not initiate a clipboard write`);
    assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, beforeAudits,
      `${stage}/${interruption}: obsolete copy must not start a session-bound audit request`);
    if (stage === 'clipboard') {
      assert.equal(clipboard, 'Please review this quotation.', 'A write already invoked may complete; Close cannot undo the physical copy');
    }
    assert.equal(dialog, currentDialog);
    assert.equal(find('[data-preview="status"]').textContent, currentStatus, 'Stale completion must not rewrite status');
    assert.equal(find('[data-preview="body"]').value, currentBody, 'Stale completion must not restore obsolete text');
    assert.equal(previousCopy.disabled, true, 'Stale completion must not re-enable obsolete approval');
    if (interruption === 'queued-close') previousDialog.events.close();
    if (interruption === 'proof-reset') assert.equal(find('[data-preview="render"]').disabled, false, 'Invalidated proof must remain regenerable');
    if (interruption === 'close' || interruption === 'new-draft') {
      await find('[data-preview="copy"]').click();
      assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, beforeAudits + 1);
      assert.equal(calls.at(-1).path, '/api/workbench/cases/case-2/drafts/draft-2/copy', 'A newer approved draft must copy and audit independently');
      assert.equal(clipboard, 'Please review the second quotation.');
      assert.equal(calls.at(-1).body.preview_id, 'render_' + 'c'.repeat(32));
      assert.match(find('[data-preview="status"]').textContent, /^Copied and recorded\./);
    }
    dialog.close();
  }
}

// If the audit was already invoked while the reviewed dialog was current, Close does
// not cancel that request or the completed clipboard write. Its response cannot touch a new draft.
await openManual();
await find('[data-preview="approve"]').click();
pendingCopy = {...deferred(), started: deferred()};
const priorDialog = dialog;
const priorCopy = find('[data-preview="copy"]');
const beforePendingAudit = calls.filter(x => x.path.endsWith('/copy')).length;
const auditCopying = priorCopy.click();
await pendingCopy.started.promise;
await priorCopy.click();
assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, beforePendingAudit + 1, 'An audit in flight must deduplicate repeated clicks');
assert.equal(clipboard, 'Please review this quotation.', 'The physical copy has already completed before Close');
priorDialog.close();
await openManual(undefined, 'draft-2');
const pendingAuditStatus = find('[data-preview="status"]').textContent;
pendingCopy.resolve({status: 'copied', delivery_claim: false});
pendingCopy = null;
await auditCopying;
assert.equal(calls.filter(x => x.path.endsWith('/copy')).length, beforePendingAudit + 1, 'Do not retry or undo an audit already initiated while current');
assert.equal(priorCopy.disabled, true);
assert.equal(find('[data-preview="copy"]').disabled, true, 'Old audit completion must not approve the new draft');
assert.equal(find('[data-preview="status"]').textContent, pendingAuditStatus);

// A current copy whose audit fails remains truthful and retryable with the same key.
await find('[data-preview="approve"]').click();
copyFails = true;
await find('[data-preview="copy"]').click();
const failedAudit = calls.at(-1);
assert.match(find('[data-preview="status"]').textContent, /^Copied, but the copy audit was not confirmed\./);
assert.equal(find('[data-preview="copy"]').disabled, false);
copyFails = false;
await find('[data-preview="copy"]').click();
assert.equal(calls.at(-1).headers['Idempotency-Key'], failedAudit.headers['Idempotency-Key'], 'An uncertain audit retry must reuse its key');
assert.deepEqual(calls.at(-1).body, failedAudit.body, 'Retry must bind the same exact preview and digest');
assert.match(find('[data-preview="status"]').textContent, /^Copied and recorded\./);
dialog.close();
console.log('Localized preview identity, approval callback readiness, repeated clicks, clipboard denial, email isolation, no-body persistence, stale digest/clipboard boundaries, in-flight audit isolation and audit retry tests passed.');
