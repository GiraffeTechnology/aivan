import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('async function confirmRelay(');
const end = source.indexOf('async function loadHealth(', start);
assert.ok(start >= 0 && end > start);

function harness() {
  const events = [];
  const state = {session: {}, authGeneration: 1, relayRequestGeneration: 1};
  const button = {disabled: false};
  const form = {dataset: {draftId: 'draft-1', caseId: 'case-1', channel: 'wechat',
    previewId: 'preview-1', contentSha256: 'a'.repeat(64)},
    receipt: 'manual-reference-1', querySelector: () => button};
  const valid = {status: 'relayed', idempotent_replay: false, receipt: {
    receipt_id: 'receipt-1', draft_id: 'draft-1', case_id: 'case-1', channel: 'wechat',
    receipt_reference: form.receipt, confirmed_by: 'operator-1', confirmed_at: '2026-10-18T00:00:00Z',
  }};
  let response = valid;
  let requestCount = 0;
  const ctx = vm.createContext({state, t: value => value,
    requestId: () => `relay-request-${++requestCount}`,
    $$: () => [], history: {replaceState() {}}, window: {scrollTo() {}},
    loadCases() {}, loadHealth() {},
    FormData: class {constructor(target) {this.target = target;} get() {return this.target.receipt;}},
    api: async (path, options) => {
      events.push({path, options});
      return typeof response === 'function' ? response() : response;
    },
    toast: (message, kind) => events.push({message, kind}),
    loadRelay: async () => events.push('reload'),
  });
  vm.runInContext(source.slice(start, end), ctx);
  vm.runInContext(source.slice(source.indexOf('function setView('), source.indexOf('function populateRoles(')), ctx);
  return {state, events, valid, form, button,
    submit: () => ctx.confirmRelay({preventDefault() {}, target: form}),
    response(value) {response = value;}, navigate: name => ctx.setView(name)};
}

for (const response of [null, {}, {status: 'sent'}, {status: 'relayed'},
  {status: 'relayed', idempotent_replay: false, receipt: {draft_id: 'other-draft'}}]) {
  const h = harness(); h.response(response); await h.submit();
  assert.equal(h.events.filter(e => e.kind === 'success').length, 0, 'missing/mismatched receipt is not a recorded manual send');
  assert.ok(!h.events.includes('reload'));
}
for (const patch of [{draft_id: 'other'}, {case_id: 'other'}, {channel: 'email'},
  {receipt_id: ''}, {confirmed_at: ''}, {confirmed_by: ''}]) {
  const h = harness(); h.response({...h.valid, receipt: {...h.valid.receipt, ...patch}}); await h.submit();
  assert.equal(h.events.filter(e => e.kind === 'success').length, 0);
}
for (const replay of [false, true]) {
  const h = harness(); h.response({...h.valid, idempotent_replay: replay}); await h.submit();
  assert.equal(h.events.filter(e => e.kind === 'success').length, 1);
  assert.equal(h.events.at(-1), 'reload');
  const request = h.events.find(e => e.path);
  assert.equal(request.options.headers['Idempotency-Key'], 'relay-request-1');
  const body = JSON.parse(request.options.body);
  assert.equal(body.preview_id, 'preview-1');
  assert.equal(body.content_sha256, 'a'.repeat(64));
  assert.equal(h.form.dataset.relayKey, undefined);
}
{
  const h = harness(); h.response(() => {throw Error('private remote response');}); await h.submit();
  assert.equal(h.form.dataset.relayKey, 'relay-request-1', 'uncertain retry keeps its key');
  assert.ok(!h.events.at(-1).message.includes('private remote'));
  h.response(h.valid); await h.submit();
  assert.equal(h.events.filter(e => e.path)[1].options.headers['Idempotency-Key'], 'relay-request-1');
}
{
  const h = harness(); h.form.receipt = ' '; await h.submit();
  assert.equal(h.events.filter(e => e.path).length, 0);
}
for (const change of [h => {h.state.session = null;}, h => {h.state.authGeneration++;},
  h => {h.navigate('dashboard');}]) {
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); change(h); release(h.valid); await pending;
  assert.equal(h.events.filter(e => e.kind).length, 0);
  assert.ok(!h.events.includes('reload'), 'stale view/session must not reload another context');
}
{
  const h = harness(); h.response(() => {throw Error('uncertain');});
  await h.submit(); h.form.receipt = 'corrected-reference'; await h.submit();
  assert.equal(h.events.filter(e => e.path)[1].options.headers['Idempotency-Key'], 'relay-request-2',
    'changed payload must not silently reuse the prior request identity');
}
{
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); await h.submit();
  assert.equal(h.events.filter(e => e.path).length, 1);
  release(h.valid); await pending;
  assert.equal(h.button.disabled, false);
}
assert.ok(source.includes('data-case-id="${escapeHtml(item.project_id)}" data-channel="${escapeHtml(item.channel)}"'),
  'the rendered form must carry the actual draft case/channel, not guessed identities');
console.log('Manual relay receipt identity, unknown outcome, retry key, stale view and duplicate submission checks passed.');
