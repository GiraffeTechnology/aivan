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
let dialog, clipboardFails = false, clipboard = '', heldApproval = null, pendingRender = null;
const french = '\u0042\u006f\u006e\u006a\u006f\u0075\u0072\u002c\u0020\u0076\u006f\u0069\u0063\u0069\u0020\u0076\u006f\u0074\u0072\u0065\u0020\u0064\u0065\u0076\u0069\u0073\u002e';
function proof(language, manual) {
  const message = language === 'en' ? 'Please review this quotation.' : french;
  return {preview_id: 'render_' + 'a'.repeat(32), draft_id: 'draft-1', case_id: 'case-1',
    target_language: language, manual_delivery: manual, approval_required: true,
    channel: 'email', sender: 'sender@example.invalid', recipient: 'buyer@example.invalid',
    source_sha256: 'b'.repeat(64), rendered_sha256: createHash('sha256').update(message).digest('hex'), message_text: message};
}
const api = async (path, options) => {
  const body = JSON.parse(options.body); calls.push({path, body});
  if (path.endsWith('/preview')) {
    if (pendingRender) return pendingRender;
    return proof(body.target_language, body.manual_delivery);
  }
  if (path.endsWith('/approve')) return heldApproval;
  if (path.endsWith('/copy')) return {status: 'copied', delivery_claim: false};
  throw Error('Unexpected endpoint');
};
const window = {};
const context = vm.createContext({window, crypto: webcrypto, TextEncoder, Uint8Array,
  navigator: {clipboard: {writeText: async value => { if (clipboardFails) throw Error('denied'); clipboard = value; }}},
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
console.log('Localized preview identity, repeated clicks, clipboard denial, no-body persistence and stale-close tests passed.');
