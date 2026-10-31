// Real host source/context/binding with controlled fetch and a synthetic mount.
// Node unit evidence; not a browser, live identity, or MySQL acceptance claim.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import {createHash} from 'node:crypto';

const staticRoot = new URL('../src/aivan/app/static/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, staticRoot), 'utf8');
const assets = JSON.parse(read('r6-execution-assets.json'));
const bundleName = Object.keys(assets.assets).find(name => name.endsWith('.js'));
const app = read('app.js');
const order = '11111111-1111-4111-8111-111111111111';
const project = '22222222-2222-4222-8222-222222222222';
const shipment = '33333333-3333-4333-8333-333333333333';
const caseId = 'case:apparel-1';
const association = (overrides = {}) => ({
  schema_version: 'aivan.execution-association.v1', case_id: caseId,
  status: 'associated', readback_verified: true, execution_reads_available: true,
  execution_read_prefix: '/api/workbench/cases/case%3Aapparel-1/execution',
  execution_readiness: 'not_checked',
  local_order_id: order, local_project_id: project, ...overrides,
});
function selected(start, end) {
  const a = app.indexOf(start), b = app.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'Actual host function exists');
  return app.slice(a, b);
}
function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return {promise, resolve};
}
function harness() {
  const nodes = new Map();
  const node = name => {
    if (!nodes.has(name)) nodes.set(name, {dataset: {}, textContent: '', innerHTML: '', hidden: false});
    return nodes.get(name);
  };
  const calls = [], updates = [], transitions = [], listeners = new Map();
  const state = {session: {role: 'admin'}, authGeneration: 1, caseRequestGeneration: 1,
    executionHost: null, executionBinding: null};
  let current = null, unmounts = 0, nextAssociation = async () => association();
  let nextResource = async () => new Response('denied', {status: 403});
  const ctx = vm.createContext({AbortController, AbortSignal, DOMException, Response, Headers,
    URL, URLSearchParams, setTimeout, clearTimeout, console, state, $: node, $$: () => [],
    t: value => value, populateRoles() {},
    requestId: () => 'synthetic-session', cookie: () => '', clearLocalInputs() {},
    releaseInquirySubmission() {}, history: {replaceState() {}},
    location: {origin: 'https://host.invalid', hash: '', pathname: '/', search: ''},
    fetch: async (url, options) => {
      calls.push({url, options});
      if (String(url).endsWith('/execution-association')) {
        const value = await nextAssociation();
        return new Response(JSON.stringify(value), {headers: {'content-type': 'application/json'}});
      }
      return nextResource(url, options);
    },
  });
  vm.runInContext('window = globalThis; window.scrollTo = () => {};', ctx);
  ctx.addEventListener = (name, callback) => listeners.set(name, callback);
  vm.runInContext(read(bundleName), ctx);
  assert.equal(typeof ctx.myAivanR6Execution.mountExecutionHost, 'function');
  const realBind = ctx.myAivanR6Execution.bindExecutionHost;
  ctx.myAivanR6Execution = {bindExecutionHost: realBind, mountExecutionHost: () => ({
    update(value) { current = value; updates.push(value); transitions.push('ready'); },
    logout() { current = null; transitions.push('cleared'); },
    unmount() { current = null; unmounts++; transitions.push('unmounted'); },
  })};
  vm.runInContext(read('execution-host-context.js'), ctx);
  vm.runInContext(read('r6-execution-host.js'), ctx);
  vm.runInContext([
    selected('async function api(', '\nfunction showLogin('),
    selected('function showLogin(', '\nfunction showApp('),
    selected('function invalidateCaseView(', '\nfunction populateRoles('),
    selected('async function loadExecutionAssociation(', '\nfunction draftRow('),
    app.slice(app.lastIndexOf("window.addEventListener('pagehide'")),
  ].join('\n'), ctx);
  return {ctx, state, calls, updates, transitions, listeners, node,
    current: () => current, unmounts: () => unmounts,
    associationWith(fn) { nextAssociation = fn; }, resourceWith(fn) { nextResource = fn; },
    load: (id = caseId, isCurrent = () => true) => ctx.loadExecutionAssociation(id, isCurrent)};
}

test('pinned emitted assets retain their recorded hashes and loadable exports', () => {
  for (const [name, record] of Object.entries(assets.assets)) {
    const bytes = fs.readFileSync(new URL(name, staticRoot));
    assert.equal(bytes.length, record.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), record.sha256);
  }
  harness();
});

test('actual HTML loads one persistent container and dependencies before the app', () => {
  const html = fs.readFileSync(new URL('../src/aivan/app/templates/index.html', import.meta.url), 'utf8');
  assert.equal((html.match(/id="r6-execution-workspace"/g) || []).length, 1);
  const names = ['execution-host-context.js', bundleName, 'r6-execution-host.js', 'app.js'];
  const positions = names.map(name => html.indexOf(`src="/static/${name}" defer`));
  assert.ok(positions.every((position, index) => position >= 0 && (!index || position > positions[index - 1])));
  const css = Object.keys(assets.assets).find(name => name.endsWith('.css'));
  assert.ok(html.includes(`href="/static/${css}"`));
});

test('approved route vocabulary is bound to the exact associated order and case', () => {
  const h = harness(), resolve = h.ctx.myAivanR6Host.createReadResolver(caseId, association());
  const prefix = '/api/workbench/cases/case%3Aapparel-1/execution';
  for (const [path, suffix] of [
    [`/api/orders/${order}`, '/order'],
    [`/api/orders/${order}/production-monitoring`, '/production'],
    [`/api/orders/${order}/qc-records`, '/qc'],
    [`/api/execution-graph/orders/${order}`, '/events'],
    [`/api/shipments/${shipment}`, `/shipments/${shipment}`],
  ]) assert.equal(resolve(path), prefix + suffix);
  for (const path of [null, '', `/api/orders/${project}`, `/api/orders/${order}?x=1`,
    `/api/orders/${order}/`, `/api/orders/${order}#x`, `/api/orders/${order}/../${project}`,
    `/api/orders/%31${order.slice(1)}`, `/api/shipments/${shipment}?x=1`,
    '/api/shipments/not-a-uuid', '/api/shipments/', '/api/orders',
    `https://host.invalid/api/orders/${order}`, `//host.invalid/api/orders/${order}`,
    `/api/orders/${order}/signoff`, '/api/installation/session']) {
    assert.throws(() => resolve(path), /EXECUTION_READ_PATH_UNAVAILABLE/);
  }
});

test('unavailable, unverified and malformed associations never activate an order', async () => {
  for (const change of [{execution_reads_available: false}, {execution_reads_available: 'true'},
    {readback_verified: false}, {readback_verified: 'true'}, {status: 'unavailable'},
    {local_order_id: 'provider-po-1'}, {local_project_id: null}, {case_id: 'foreign-case'},
    {execution_read_prefix: undefined},
    {execution_read_prefix: '/api/workbench/cases/foreign-case/execution'},
    {execution_read_prefix: 'https://host.invalid/api/workbench/cases/case%3Aapparel-1/execution'},
    {execution_read_prefix: '/api/workbench/cases/case%3Aapparel-1/execution?proxy=1'},
    {schema_version: 'unknown'}]) {
    const h = harness(); h.associationWith(async () => association(change)); await h.load();
    assert.ok(h.current() === null || h.current().orderId === null);
    assert.equal(h.calls.length, 1);
    assert.ok(!h.updates.some(value => value.orderId !== null));
    assert.doesNotMatch(h.node('#execution-association-status').textContent, /^Verified order/);
  }
});

test('actual association loader binds once and retains native HTTP errors and signal', async () => {
  const h = harness(); await h.load();
  assert.equal(h.current().orderId, order);
  const response = new Response('not found', {status: 404});
  h.resourceWith(async () => response);
  const abort = new AbortController();
  const actual = await h.current().request(`/api/orders/${order}`, {method: 'GET', signal: abort.signal});
  assert.equal(actual, response);
  assert.equal(actual.status, 404);
  const request = h.calls.at(-1);
  assert.equal(request.url, 'https://host.invalid/api/workbench/cases/case%3Aapparel-1/execution/order');
  assert.equal(request.options.credentials, 'same-origin');
  assert.equal(request.options.redirect, 'error');
  assert.equal(request.options.method, 'GET');
  assert.equal(request.options.cache, 'no-store');
  abort.abort(); assert.equal(request.options.signal.aborted, true);
  await assert.rejects(h.current().request(`/api/orders/${order}`, {method: 'POST', signal: new AbortController().signal}), /GET and AbortSignal/);
  assert.equal(h.calls.length, 2);
  await h.load(); assert.equal(h.unmounts(), 0, 'A refresh reuses the single binding');
});

test('case invalidation clears the mounted view synchronously and discards late resources', async () => {
  const h = harness(); await h.load();
  const pending = deferred(); h.resourceWith(() => pending.promise);
  const request = h.current().request(`/api/orders/${order}`, {method: 'GET', signal: new AbortController().signal});
  const rejection = assert.rejects(request, {name: 'AbortError'});
  h.ctx.invalidateCaseView();
  assert.equal(h.current(), null);
  assert.equal(h.calls.at(-1).options.signal.aborted, true);
  pending.resolve(new Response('stale')); await rejection;
});

test('logout/session replacement while association is pending cannot activate stale order', async () => {
  for (const transition of ['logout', 'session', 'case']) {
    const h = harness(), pending = deferred(); h.associationWith(() => pending.promise);
    const original = h.state.session;
    const loading = h.load(caseId, () => h.state.session === original && h.state.caseRequestGeneration === 1);
    if (transition === 'logout') { h.ctx.showLogin(); h.state.session = null; }
    else if (transition === 'session') { h.state.session = {role: 'auditor'}; h.state.executionHost.invalidate('context-changing'); }
    else h.ctx.invalidateCaseView();
    pending.resolve(association()); await loading;
    assert.equal(h.current(), null);
    assert.equal(h.updates.length, 0);
  }
});

test('showLogin synchronously clears an already mounted order', async () => {
  const h = harness(); await h.load(); h.ctx.showLogin();
  assert.equal(h.current(), null);
  assert.equal(h.state.executionHost.source.snapshot().reason, 'signed-out');
});

test('pagehide clears bfcache view and releases the binding only on real unload', async () => {
  const h = harness(); await h.load();
  h.listeners.get('pagehide')({persisted: true});
  assert.equal(h.current(), null); assert.equal(h.unmounts(), 0);
  await h.load(); h.listeners.get('pagehide')({persisted: false});
  assert.equal(h.current(), null); assert.equal(h.unmounts(), 1);
  assert.equal(h.state.executionHost, null); assert.equal(h.state.executionBinding, null);
});

test('missing immutable runtime fails closed without association or execution requests', async () => {
  const h = harness(); h.ctx.myAivanR6Execution = null;
  await h.load(); assert.equal(h.current(), null); assert.equal(h.calls.length, 0);
  assert.match(h.node('#execution-association-status').textContent, /Association read failed/);
});

for (const transition of ['login', 'restore']) {
  test(`${transition} adoption clears a mounted order before pending bootstrap returns`, {timeout: 3000}, async () => {
    const h = harness(); await h.load();
    assert.equal(h.current().orderId, order);
    const started = deferred(), bootstrap = deferred();
    h.ctx.loadBootstrap = () => { started.resolve(); return bootstrap.promise; };
    h.ctx.loadCases = async () => {}; h.ctx.loadHealth = async () => {};
    h.ctx.setView = () => {};
    const session = {role: 'admin', allowed_roles: ['admin'], csrf_token: 'synthetic-csrf', test_account: false};
    h.resourceWith(async () => new Response(JSON.stringify(session), {headers: {'content-type': 'application/json'}}));
    vm.runInContext([
      selected('function showApp(', '\nfunction setView('),
      selected('async function establishSession(', '\nasync function login('),
      selected('async function login(', '\nasync function logout('),
    ].join('\n'), h.ctx);
    h.node('#access-key').value = 'synthetic-key'; h.node('#tenant-id').value = 'synthetic-tenant';
    const pending = transition === 'login'
      ? h.ctx.login({preventDefault() {}, submitter: {disabled: false}})
      : h.ctx.establishSession();
    await started.promise;
    try { assert.equal(h.current(), null, 'Old order must be gone at session adoption, before any later API completes'); }
    finally { bootstrap.resolve(); await pending; }
  });
}

test('a superseded session restore cannot clear the newer mounted order', async () => {
  for (const supersededBy of ['generation', 'session']) {
  const h = harness(); await h.load();
  const pending = deferred(); h.resourceWith(() => pending.promise);
  vm.runInContext(selected('async function establishSession(', '\nasync function login('), h.ctx);
  const restoring = h.ctx.establishSession();
  const newerSession = {role: 'admin', marker: 'newer-session'};
  if (supersededBy === 'generation') h.state.authGeneration += 1;
  h.state.executionHost.invalidate('context-changing');
  h.state.session = newerSession;
  await h.load();
  const newerContext = h.current();
  assert.equal(newerContext.orderId, order);
  pending.resolve(new Response(JSON.stringify({role: 'admin'}), {headers: {'content-type': 'application/json'}}));
  await restoring;
  assert.equal(h.state.session, newerSession);
  assert.equal(h.current(), newerContext, 'Stale restore failure must not sign out or clear the newer lifetime');
  }
});

test('a current session restore denial still clears the mounted order', async () => {
  for (const status of [401, 403, 500]) {
    const h = harness(); await h.load();
    h.resourceWith(async () => new Response(JSON.stringify({detail: 'synthetic failure'}),
      {status, headers: {'content-type': 'application/json'}}));
    vm.runInContext(selected('async function establishSession(', '\nasync function login('), h.ctx);
    await h.ctx.establishSession();
    assert.equal(h.current(), null);
    assert.equal(h.node('#login-view').hidden, false);
    assert.equal(h.node('#app-shell').hidden, true);
  }
});

test('a superseded login response cannot replace or clear the newer host lifetime', async () => {
  for (const replaceGeneration of [false, true]) {
    for (const result of ['success', 'denied', 'invalid-json']) {
      const h = harness(); await h.load();
      const pending = deferred(); h.resourceWith(() => pending.promise);
      vm.runInContext(selected('async function login(', '\nasync function logout('), h.ctx);
      h.node('#access-key').value = 'synthetic-key'; h.node('#tenant-id').value = 'synthetic-tenant';
      const loggingIn = h.ctx.login({preventDefault() {}, submitter: {disabled: false}});
      const newerSession = {role: 'admin', marker: 'newer-session'};
      if (replaceGeneration) h.state.authGeneration += 1;
      h.state.executionHost.invalidate('context-changing'); h.state.session = newerSession;
      await h.load(); const newerContext = h.current();
      pending.resolve(new Response(result === 'invalid-json' ? '{' : JSON.stringify({role: 'admin', detail: {error: 'synthetic denial'}}),
        {status: result === 'denied' ? 403 : 200, headers: {'content-type': 'application/json'}}));
      await loggingIn;
      assert.equal(h.state.session, newerSession, 'A superseded login must not adopt its old response');
      assert.equal(h.current(), newerContext, 'A superseded login must not clear the newer host');
    }
  }
});

test('a current login denial still clears the mounted order', async () => {
  const h = harness(); await h.load();
  vm.runInContext(selected('async function login(', '\nasync function logout('), h.ctx);
  h.node('#access-key').value = 'synthetic-key'; h.node('#tenant-id').value = 'synthetic-tenant';
  h.resourceWith(async () => new Response(JSON.stringify({detail: {error: 'synthetic denial'}}),
    {status: 403, headers: {'content-type': 'application/json'}}));
  await h.ctx.login({preventDefault() {}, submitter: {disabled: false}});
  assert.equal(h.current(), null);
  assert.equal(h.node('#login-view').hidden, false);
  assert.equal(h.node('#app-shell').hidden, true);
});
