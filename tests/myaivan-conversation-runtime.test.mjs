import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const app = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../src/aivan/app/templates/index.html', import.meta.url), 'utf8');
assert.ok(html.indexOf('id="conversation-stream"') < html.indexOf('id="outbound-review"'));
assert.ok(html.indexOf('id="conversation-stream"') >= 0, 'Conversation region is required');
assert.ok(html.indexOf('id="outbound-review"') < html.indexOf('id="inquiry-form"'));
const start = app.indexOf('async function showInquiryConversation(');
assert.ok(start >= 0);
const nodes = {
  '#conversation-stream': { children: [], replaceChildren() { this.children = []; }, append(node) { this.children.push(node); } },
  '#outbound-review-content': { textContent: '', innerHTML: '' },
};
let fail = false;
let calls = 0;
const ctx = vm.createContext({
  $: selector => nodes[selector],
  document: { createElement: () => ({textContent: '', className: ''}) },
  api: async path => { calls++; assert.equal(path, '/api/workbench/cases/case-1'); if(fail) throw Error('private detail'); return {drafts: [{draft_id:'d1'}]}; },
  draftRow: draft => `<article>${draft.draft_id}</article>`,
});
vm.runInContext(app.slice(start, app.indexOf('function inquirySubmissionOutcome(', start)), ctx);
await ctx.showInquiryConversation('case-1', '<img onerror=bad>', 'Accepted, not sent');
assert.equal(nodes['#conversation-stream'].children[0].textContent, '<img onerror=bad>');
assert.equal(nodes['#conversation-stream'].children[0].className, 'conversation-message user-message');
assert.equal(nodes['#conversation-stream'].children[1].className, 'conversation-message assistant-message');
assert.equal(nodes['#outbound-review-content'].innerHTML, '<article>d1</article>');
fail = true;
await ctx.showInquiryConversation('case-1', 'Revision', 'Accepted');
assert.match(nodes['#outbound-review-content'].textContent, /could not be loaded/);
assert.ok(!nodes['#outbound-review-content'].textContent.includes('private detail'));
assert.equal(calls, 2);
console.log('Conversation layout/readback/failure/plain-text checks passed (local only).');

// Exercise the actual delegated handlers, rather than calling confirmOrder directly.
const delegated = new Map();
const navigation = [];
const confirmations = [];
const posts = [];
let accepted = true;
const actionContext = vm.createContext({
  document: { addEventListener(type, listener) { delegated.set(type, listener); } },
  window: { confirm(message) { confirmations.push(message); return accepted; } },
  t: value => value, toast() {}, setView() {},
  openCase: async caseId => navigation.push(caseId),
  api: async (path, request) => { posts.push({ path, request }); return { recovered: false }; },
});
const confirmStart = app.indexOf('async function confirmOrder(');
vm.runInContext(app.slice(confirmStart, app.indexOf('async function copyDraftText(', confirmStart)), actionContext);
const clickStart = app.indexOf("document.addEventListener('click', async (event) => {");
vm.runInContext(app.slice(clickStart, app.indexOf("document.addEventListener('submit'", clickStart)), actionContext);
assert.match(app, /data-action="confirm-order" data-case-id="\$\{escapeHtml\(item.case_id\)\}" data-option-id=/);
const action = {
  dataset: { action: 'confirm-order', caseId: 'case-confirm', optionId: 'selected-option' },
  closest(selector) { return ['[data-case-id]', '[data-action]'].includes(selector) ? this : null; },
};
// A nested icon has the same nearest action button.
const nestedTarget = { closest: selector => action.closest(selector) };
await delegated.get('click')({ target: nestedTarget });
assert.equal(confirmations.length, 1, 'the actual click must reach the explicit human confirmation');
assert.equal(posts.length, 1);
assert.equal(posts[0].path, '/api/workbench/cases/case-confirm/order-confirmation');
assert.equal(posts[0].request.method, 'POST');
assert.deepEqual(JSON.parse(posts[0].request.body), { selected_option_id: 'selected-option' });
assert.deepEqual(navigation, ['case-confirm'], 'refresh only after successful confirmation');
accepted = false;
await delegated.get('click')({ target: action });
assert.equal(confirmations.length, 2);
assert.equal(posts.length, 1, 'cancel must not submit or navigate');
assert.equal(navigation.length, 1);
let prevented = false;
delegated.get('keydown')({ target: action, key: 'Enter', preventDefault() { prevented = true; } });
assert.equal(prevented, false, 'native action-button activation must not be intercepted as card navigation');
assert.equal(navigation.length, 1);
const card = {
  dataset: { caseId: 'case-card' },
  closest(selector) { return ['[data-case-id]', '.case-card[data-case-id]'].includes(selector) ? this : null; },
};
await delegated.get('click')({ target: card });
delegated.get('keydown')({ target: card, key: 'Enter', preventDefault() { prevented = true; } });
assert.equal(prevented, true);
assert.deepEqual(navigation, ['case-confirm', 'case-card', 'case-card']);
assert.equal(posts.length, 1);
console.log('Actual confirmation click/cancel/button keyboard and case-card navigation checks passed.');
