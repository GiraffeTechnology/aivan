import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
function selected(name, end) {
  const begin = source.indexOf(`async function ${name}(`);
  const finish = source.indexOf(end, begin);
  assert.ok(begin >= 0 && finish > begin);
  return source.slice(begin, finish);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
const rows = id => ({items: [{case_id: id}], page: {total: 50, has_more: true}});
const health = backend => ({database: {configured: true}, gpm: {backend, durable_required: true},
  openclaw: {configured: false}, model: {configured: false}, candidate_sha: 'a'.repeat(40)});
const bootstrap = {candidate_sha: 'a'.repeat(40), api_version: '0.3.0', actor: {actor_id: 'current'}};
function harness() {
  const state = {session: {role: 'sales'}, authGeneration: 1, offset: 0, limit: 20,
    cases: [], total: 0, bootstrap: null};
  const nodes = new Map(), requests = [], metrics = [], validations = [];
  let validate = async () => {};
  const node = name => {
    if (!nodes.has(name)) nodes.set(name, {innerHTML: `INITIAL:${name}`, textContent: '', value: '', disabled: false});
    return nodes.get(name);
  };
  const ctx = vm.createContext({state, Headers, URLSearchParams, $: node, t: x => x, ht: x => x,
    escapeHtml: x => String(x ?? ''), emptyHtml: () => 'EMPTY', caseCard: item => `CASE:${item.case_id}`,
    renderMetrics: items => metrics.push(items), requestId: () => 'unused-get-id', cookie: () => '',
    window: {myAivanI18n: {assertCandidate: value => {validations.push(value); return validate(value);}}},
    // Only HTTP completion is controlled. The production api() below is not replaced.
    fetch: (path, options) => {
      const response = deferred(), body = deferred(), parsing = deferred();
      const entry = {path, options, response, body, parsing}; requests.push(entry);
      entry.respond = (status = 200) => response.resolve({ok: status >= 200 && status < 300, status,
        headers: new Headers({'content-type': 'application/json'}),
        json: () => {parsing.resolve(); return body.promise;}});
      return response.promise;
    },
  });
  vm.runInContext([
    selected('api', '\nfunction showLogin('),
    selected('loadBootstrap', '\nfunction caseCard('),
    selected('loadCases', '\nfunction renderMetrics('),
    selected('loadHealth', '\ndocument.addEventListener('),
  ].join('\n'), ctx);
  const reply = async (request, payload, status = 200) => {
    request.respond(status); await request.parsing.promise; request.body.resolve(payload);
  };
  return {state, node, requests, metrics, validations, ctx, reply, validateWith: fn => {validate = fn;}};
}

test('production api GET and current loader render real parsed payload', async () => {
  const h = harness(), pending = h.ctx.loadCases(true);
  await h.reply(h.requests[0], rows('current')); await pending;
  assert.equal(h.requests[0].options.credentials, 'same-origin');
  assert.equal(h.requests[0].options.method, 'GET');
  assert.equal(h.state.cases[0].case_id, 'current');
  assert.equal(h.metrics.length, 1);
});

test('late fetch after logout cannot paint either old records or a stale-session error', async () => {
  const h = harness(), pending = h.ctx.loadCases(true);
  h.state.session = null; h.state.authGeneration++;
  // A transport-guarded api rejects before parsing; an older unguarded api parses normally.
  h.requests[0].respond(); h.requests[0].body.resolve(rows('previous-tenant'));
  await pending;
  assert.equal(h.state.cases.length, 0);
  assert.equal(h.node('#case-list').innerHTML, 'INITIAL:#case-list');
  assert.equal(h.metrics.length, 0);
});

test('session change while JSON parses cannot paint old records or its rejection', async () => {
  const h = harness(), pending = h.ctx.loadCases(true);
  h.requests[0].respond(); await h.requests[0].parsing.promise;
  h.state.session = {role: 'buyer'}; h.state.authGeneration++;
  h.requests[0].body.resolve(rows('previous-tenant')); await pending;
  assert.equal(h.state.cases.length, 0);
  assert.equal(h.node('#case-list').innerHTML, 'INITIAL:#case-list');
});

test('real api does not prevent stale same-session page responses: loader must guard them', async () => {
  const h = harness(), first = h.ctx.loadCases();
  h.state.offset = 20; const second = h.ctx.loadCases();
  await h.reply(h.requests[1], rows('latest')); await second;
  await h.reply(h.requests[0], rows('older')); await first;
  assert.equal(h.state.cases[0].case_id, 'latest');
  assert.ok(h.node('#page-summary').textContent.startsWith('21-'));
});

test('session adoption during post-api candidate validation cannot publish bootstrap', async () => {
  const h = harness(), started = deferred(), hold = deferred();
  h.validateWith(() => {started.resolve(); return hold.promise;});
  const pending = h.ctx.loadBootstrap(); await h.reply(h.requests[0], bootstrap);
  await started.promise;
  h.state.session = {role: 'buyer'}; h.state.authGeneration++;
  hold.resolve(); await pending;
  assert.equal(h.state.bootstrap, null);
  assert.equal(h.node('#candidate-banner').innerHTML, 'INITIAL:#candidate-banner');
});

test('current bootstrap still publishes after real api and candidate validation', async () => {
  const h = harness(), pending = h.ctx.loadBootstrap();
  await h.reply(h.requests[0], bootstrap); await pending;
  assert.equal(h.state.bootstrap, bootstrap);
  assert.equal(h.validations.length, 1);
});

test('older health network rejection cannot replace latest successful current health', async () => {
  const h = harness(), old = h.ctx.loadHealth(), current = h.ctx.loadHealth();
  await h.reply(h.requests[1], health('current-backend')); await current;
  h.requests[0].response.reject(new Error('synthetic-old-network-failure')); await old;
  assert.ok(h.node('#health-grid').innerHTML.includes('current-backend'));
  assert.ok(!h.node('#health-grid').innerHTML.includes('synthetic-old-network-failure'));
});

test('current HTTP denial remains a visible failure, not silently treated as stale', async () => {
  const h = harness(), pending = h.ctx.loadCases();
  await h.reply(h.requests[0], {detail: {error: 'ROLE_FORBIDDEN'}}, 403); await pending;
  assert.ok(h.node('#case-list').innerHTML.includes('ROLE_FORBIDDEN'));
  assert.equal(h.state.cases.length, 0);
});
