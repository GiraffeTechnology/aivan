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
