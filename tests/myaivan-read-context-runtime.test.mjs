import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
function selected(name, endMarker) {
  const start = source.indexOf(`async function ${name}(`);
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
const cases = id => ({items: [{case_id: id}], page: {total: 50, has_more: true}});
const bootstrap = {candidate_sha: 'a'.repeat(40), api_version: '0.3.0', actor: {actor_id: 'current'}};
const health = backend => ({database: {configured: true}, gpm: {durable_required: true, backend},
  openclaw: {configured: false}, model: {configured: false}, candidate_sha: 'a'.repeat(40)});
function harness() {
  const state = {session: {role: 'sales'}, authGeneration: 1, cases: [], total: 0,
    offset: 0, limit: 20, bootstrap: null};
  const nodes = new Map();
  const node = key => {
    if (!nodes.has(key)) nodes.set(key, {innerHTML: `INITIAL:${key}`, textContent: '', value: '', disabled: false});
    return nodes.get(key);
  };
  const requests = [], validations = [], metrics = [];
  let validate = async () => {};
  const ctx = vm.createContext({state, URLSearchParams,
    $: node, t: value => value, ht: value => value, escapeHtml: value => String(value),
    caseCard: item => `CASE:${item.case_id}`, emptyHtml: () => 'EMPTY',
    renderMetrics: items => metrics.push(items),
    window: {myAivanI18n: {assertCandidate: sha => {validations.push(sha); return validate(sha);}}},
    api: path => {const pending = deferred(); requests.push({path, ...pending}); return pending.promise;},
  });
  vm.runInContext([
    selected('loadBootstrap', 'function caseCard('),
    selected('loadCases', 'function renderMetrics('),
    selected('loadHealth', '\ndocument.addEventListener('),
  ].join('\n'), ctx);
  return {state, node, nodes, requests, validations, metrics, ctx,
    validateWith: callback => {validate = callback;}};
}

test('active authenticated case read still renders actual returned rows', async () => {
  const h = harness(); const pending = h.ctx.loadCases(true);
  h.requests[0].resolve(cases('current')); await pending;
  assert.equal(h.state.cases[0].case_id, 'current');
  assert.ok(h.node('#case-list').innerHTML.includes('CASE:current'));
  assert.equal(h.metrics.length, 1);
});
test('case response cannot repopulate state or DOM after sign-out', async () => {
  const h = harness(); const pending = h.ctx.loadCases(true);
  h.state.session = null; h.state.authGeneration++;
  h.requests[0].resolve(cases('previous-tenant')); await pending;
  assert.equal(h.state.cases.length, 0);
  assert.ok(!h.node('#case-list').innerHTML.includes('previous-tenant'));
  assert.equal(h.metrics.length, 0);
});
test('previous-session cases cannot replace a newer authenticated read', async () => {
  const h = harness(); const old = h.ctx.loadCases(true);
  h.state.session = {role: 'buyer'}; const current = h.ctx.loadCases(true);
  h.requests[1].resolve(cases('current-tenant')); await current;
  h.requests[0].resolve(cases('previous-tenant')); await old;
  assert.equal(h.state.cases[0].case_id, 'current-tenant');
  assert.ok(!h.node('#case-list').innerHTML.includes('previous-tenant'));
});
test('controlled same-session page interleaving keeps the latest requested page', async () => {
  const h = harness(); const first = h.ctx.loadCases();
  h.state.offset = 20; const second = h.ctx.loadCases();
  h.requests[1].resolve(cases('page-two')); await second;
  h.requests[0].resolve(cases('page-one')); await first;
  assert.equal(h.state.cases[0].case_id, 'page-two');
  assert.ok(h.node('#page-summary').textContent.startsWith('21-'));
});
test('a stale case failure cannot overwrite the newer list with an error', async () => {
  const h = harness(); const old = h.ctx.loadCases();
  h.state.session = {role: 'buyer'}; const current = h.ctx.loadCases();
  h.requests[1].resolve(cases('current')); await current;
  h.requests[0].reject(new Error('previous-session-private-failure')); await old;
  assert.ok(h.node('#case-list').innerHTML.includes('CASE:current'));
  assert.ok(!h.node('#case-list').innerHTML.includes('private-failure'));
});
test('stale bootstrap cannot publish actor/candidate data or start validation', async () => {
  const h = harness(); const pending = h.ctx.loadBootstrap();
  h.state.session = null; h.requests[0].resolve(bootstrap); await pending;
  assert.equal(h.state.bootstrap, null);
  assert.equal(h.validations.length, 0);
  assert.equal(h.node('#candidate-banner').innerHTML, 'INITIAL:#candidate-banner');
});
test('bootstrap publishes only after current candidate validation finishes', async () => {
  const h = harness(), started = deferred(), gate = deferred();
  h.validateWith(() => {started.resolve(); return gate.promise;});
  const pending = h.ctx.loadBootstrap(); h.requests[0].resolve(bootstrap);
  await started.promise; assert.equal(h.state.bootstrap, null);
  gate.resolve(); await pending;
  assert.equal(h.state.bootstrap, bootstrap);
});
test('a session change during candidate validation cannot publish old bootstrap', async () => {
  const h = harness(), started = deferred(), gate = deferred();
  h.validateWith(() => {started.resolve(); return gate.promise;});
  const pending = h.ctx.loadBootstrap(); h.requests[0].resolve(bootstrap);
  await started.promise; h.state.session = {role: 'buyer'};
  gate.resolve(); await pending;
  assert.equal(h.state.bootstrap, null);
  assert.equal(h.node('#candidate-banner').innerHTML, 'INITIAL:#candidate-banner');
});
test('old bootstrap errors do not drive a new session failure handler', async () => {
  const h = harness(); const pending = h.ctx.loadBootstrap();
  h.state.session = {role: 'buyer'};
  h.requests[0].reject(new Error('previous-session-bootstrap-failure'));
  await pending;
  assert.equal(h.state.bootstrap, null);
});
test('a current bootstrap error remains a real error', async () => {
  const h = harness(); const pending = h.ctx.loadBootstrap();
  h.requests[0].reject(new Error('CURRENT_BOOTSTRAP_UNAVAILABLE'));
  await assert.rejects(pending, /CURRENT_BOOTSTRAP_UNAVAILABLE/);
});
test('old health data cannot appear in a new session', async () => {
  const h = harness(); const pending = h.ctx.loadHealth();
  h.state.session = {role: 'buyer'};
  h.requests[0].resolve(health('previous-session-backend')); await pending;
  assert.equal(h.node('#health-grid').innerHTML, 'INITIAL:#health-grid');
});
test('latest health read wins and stale health errors do not replace it', async () => {
  const h = harness(); const old = h.ctx.loadHealth(), current = h.ctx.loadHealth();
  h.requests[1].resolve(health('current-backend')); await current;
  h.requests[0].reject(new Error('previous-session-private-failure')); await old;
  assert.ok(h.node('#health-grid').innerHTML.includes('current-backend'));
  assert.ok(!h.node('#health-grid').innerHTML.includes('private-failure'));
});
test('no active session performs no authenticated workbench reads', async () => {
  const h = harness(); h.state.session = null;
  const pending = [h.ctx.loadCases(), h.ctx.loadBootstrap(), h.ctx.loadHealth()];
  assert.equal(h.requests.length, 0);
  await Promise.all(pending);
});
