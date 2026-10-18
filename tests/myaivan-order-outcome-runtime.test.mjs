import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('async function confirmOrder(');
const end = source.indexOf('async function copyDraftText(', start);
assert.ok(start >= 0 && end > start);

function harness() {
  const events = [];
  const state = {session: {}, authGeneration: 1, caseRequestGeneration: 1,
    selectedCase: {case: {case_id: 'case-1'}}};
  const valid = {status: 'confirmed', readback_verified: true, selected_option_id: 'option-1',
    purchase_order_id: 'po-1', supplier_quote_id: 'quote-1', procurement_case_id: 'procurement-1',
    rfq_id: 'rfq-1', recovered: false};
  let response = valid;
  let accepted = true;
  const context = vm.createContext({state, t: value => value,
    window: {confirm() { events.push('confirmation'); return accepted; }, scrollTo() {}},
    $$: () => [], history: {replaceState() {}},
    loadCases() {}, loadRelay() {}, loadHealth() {},
    api: async (path, options) => {
      events.push({path, body: JSON.parse(options.body)});
      return typeof response === 'function' ? response() : response;
    },
    toast: (message, kind) => events.push({message, kind}),
    openCase: async id => events.push({opened: id}),
  });
  vm.runInContext(source.slice(start, end), context);
  vm.runInContext(source.slice(source.indexOf('function setView('), source.indexOf('function populateRoles(')), context);
  return {state, valid, events, submit: () => context.confirmOrder('case-1', 'option-1'),
    response(value) { response = value; }, accept(value) { accepted = value; },
    navigate: name => context.setView(name)};
}

const invalid = [null, {}, [], {status: 'error'}, {status: 'pending'},
  {readback_verified: false}, {readback_verified: 'true'}, {selected_option_id: 'other-option'},
  {purchase_order_id: ''}, {supplier_quote_id: null}, {procurement_case_id: ''},
  {rfq_id: ''}, {recovered: 'false'}];
for (const patch of invalid) {
  const h = harness();
  h.response(patch === null || Array.isArray(patch) ? patch : {...h.valid, ...patch,
    ...(Object.keys(patch).length ? {} : {status: undefined})});
  await h.submit();
  assert.equal(h.events.filter(e => e.kind === 'success').length, 0, 'unverified response must never claim confirmation');
  assert.equal(h.events.filter(e => e.opened).length, 0, 'unverified response must not navigate as success');
  assert.equal(h.events.at(-1).kind, 'error');
}

for (const recovered of [false, true]) {
  const h = harness(); h.response({...h.valid, recovered});
  await h.submit();
  assert.equal(h.events.filter(e => e.kind === 'success').length, 1);
  assert.equal(h.events.at(-1).opened, 'case-1');
  assert.equal(h.events[1].path, '/api/workbench/cases/case-1/order-confirmation');
  assert.equal(h.events[1].body.selected_option_id, 'option-1');
}

{
  const h = harness(); h.accept(false); await h.submit();
  assert.deepEqual(h.events, ['confirmation'], 'cancel means no request or state change');
}
{
  const h = harness(); h.response(() => {throw Error('private provider response');});
  await h.submit();
  assert.equal(h.events.at(-1).kind, 'error');
  assert.ok(!h.events.at(-1).message.includes('private provider'));
}
for (const change of [h => {h.state.session = null;}, h => {h.state.authGeneration++;},
  h => {h.navigate('cases');}, h => {h.state.selectedCase = {case: {case_id: 'other-case'}};}]) {
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); change(h); release(h.valid); await pending;
  assert.equal(h.events.filter(e => e.kind || e.opened).length, 0, 'late response must not affect another session or case');
}
{
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); await h.submit();
  assert.equal(h.events.filter(e => e.path).length, 1, 'double activation must not create competing requests');
  release(h.valid); await pending;
  h.response(h.valid); await h.submit();
  assert.equal(h.events.filter(e => e.path).length, 2, 'completed attempts must release the in-flight guard');
}
console.log('Order outcome validation, explicit confirmation, races, duplicate activation and safe errors passed.');
