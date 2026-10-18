// Actual host/context/binding with synthetic mount/API; not browser or live-service acceptance.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {attachR6HostVm} from './r6-host-vm-support.mjs';

const app = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../src/aivan/app/templates/index.html', import.meta.url), 'utf8');
for (const script of ['execution-host-context.js', 'r6-execution-host.js']) {
  assert.ok(html.indexOf(`/static/${script}`) >= 0);
  assert.ok(html.indexOf(`/static/${script}`) < html.indexOf('/static/app.js'));
}
assert.ok(html.includes('id="r6-execution-workspace"'));
const nodes = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector, {textContent: '', dataset: {}});
  return nodes.get(selector);
};
const status = node('#execution-association-status');
const state = {executionHost: null, executionBinding: null};
let response, calls = 0;
const context = vm.createContext({
  window: {location: {origin: 'https://example.invalid'}},
  state, requestId: () => 'non-secret-view-id', $: node,
  api: async path => {
    calls++;
    assert.equal(path, '/api/workbench/cases/case-fixture/execution-association');
    return response;
  },
});
const view = attachR6HostVm(context);
vm.runInContext(app.slice(app.indexOf('async function loadExecutionAssociation'), app.indexOf('function draftRow')), context);
response = {schema_version: 'aivan.execution-association.v1', case_id: 'case-fixture',
  status: 'associated', readback_verified: true, execution_reads_available: false,
  local_order_id: 'must-not-activate'};
await context.loadExecutionAssociation('case-fixture', () => true);
assert.equal(calls, 1);
assert.equal(context.window.myAivanExecutionHostSource.snapshot().context.orderId, null);
assert.equal(view.updates.length, 1);
assert.equal(view.updates[0].orderId, null);
assert.match(status.textContent, /Execution reads remain unavailable/);
response = {...response, case_id: 'other-case'};
await context.loadExecutionAssociation('case-fixture', () => true);
assert.equal(calls, 2);
assert.equal(context.window.myAivanExecutionHostSource.snapshot().context, null);
assert.match(status.textContent, /read failed/);
status.textContent = 'newer-view';
response = {...response, case_id: 'case-fixture'};
await context.loadExecutionAssociation('case-fixture', () => false);
assert.equal(calls, 3);
assert.equal(status.textContent, 'newer-view');
assert.equal(view.updates.length, 1);
console.log('R6 host handoff assertions passed; synthetic mount/API, no live-service acceptance.');
