import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto, createHash } from 'node:crypto';
const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('async function copyAndRecordDraft(');
assert.ok(start >= 0, 'Successful clipboard copy needs the real audit API');
const events = [];
let clipboardOK = true;
let apiFails = false;
let apiCalls = 0;
const ctx = vm.createContext({
  crypto: webcrypto, TextEncoder,
  requestId: () => 'copy-request-1',
  copyDraftText: async () => { events.push('clipboard'); return clipboardOK; },
  toast: (message, kind) => events.push({message, kind}),
  api: async (path, options) => {
    apiCalls++;
    assert.equal(events[0], 'clipboard');
    assert.equal(path, '/api/workbench/cases/case-1/drafts/draft-1/copy');
    assert.equal(options.headers['Idempotency-Key'], 'copy-request-1');
    assert.deepEqual(Object.keys(JSON.parse(options.body)), ['content_sha256']);
    if (apiFails) throw Error('private provider detail');
    return {status: 'copied', delivery_claim: false, audit_id: 'audit-1'};
  },
});
vm.runInContext(source.slice(start, source.indexOf('async function showImpact(', start)), ctx);
const button = () => ({disabled: false, dataset: {copy: 'Actual body', copyCaseId: 'case-1',
  draftId: 'draft-1', contentSha256: createHash('sha256').update('Actual body').digest('hex')}});
let node = button();
await ctx.copyAndRecordDraft(node);
assert.equal(apiCalls, 1);
assert.equal(node.disabled, false);
assert.equal(node.dataset.copyKey, undefined);
clipboardOK = false;
await ctx.copyAndRecordDraft(button());
assert.equal(apiCalls, 1, 'Denied/manual copying must not record success');
clipboardOK = true;
node = button(); node.dataset.contentSha256 = '0'.repeat(64);
await ctx.copyAndRecordDraft(node);
assert.equal(apiCalls, 1, 'Different copied text must not be audited as the original');
apiFails = true;
node = button();
await ctx.copyAndRecordDraft(node);
assert.equal(node.dataset.copyKey, 'copy-request-1', 'Retain the key for an uncertain retry');
assert.equal(events.at(-1).kind, 'info');
assert.match(events.at(-1).message, /audit was not confirmed/);
assert.ok(!events.at(-1).message.includes('private provider'));
console.log('Copy audit ordering, denial, digest and uncertain-result tests passed (local).');
