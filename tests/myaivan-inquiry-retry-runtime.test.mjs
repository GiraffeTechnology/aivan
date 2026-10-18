import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('function inquirySubmissionOutcome(');
const end = source.indexOf('async function approveDraft(', start);
assert.ok(start >= 0 && end > start);

function harness() {
  const events = [];
  const fields = {'#buyer-id': {value: 'buyer-1'}, '#buyer-name': {value: 'Buyer One'},
    '#inquiry-text': {value: 'Please quote 100 cotton shirts.'},
    '#inquiry-result': {hidden: true, textContent: ''}};
  const state = {session: {role: 'sales'}};
  const form = {reset() {events.push('reset'); fields['#inquiry-text'].value = '';}};
  fields['#inquiry-form'] = form;
  const submitter = {disabled: false};
  let response = () => {throw Error('private connection detail');};
  let sequence = 0;
  const ctx = vm.createContext({state, JSON,
    $: selector => fields[selector], requestId: prefix => `${prefix}-${++sequence}`,
    $$: () => [], roleLabel: value => value, setView: () => {},
    loadBootstrap: async () => {}, loadHealth: async () => {},
    t: value => value, toast: (message, kind) => events.push({message, kind}),
    loadCases: async () => events.push('refresh'),
    api: async (path, options) => {
      events.push({path, options});
      if (path === '/api/session/role') return {role: 'buyer', csrf_token: 'synthetic-csrf'};
      return response();
    },
  });
  vm.runInContext(source.slice(start, end), ctx);
  const clearStart = source.indexOf('function clearLocalInputs(');
  if (clearStart >= 0) vm.runInContext(source.slice(clearStart, source.indexOf('function invalidateCaseView(', clearStart)), ctx);
  vm.runInContext(source.slice(source.indexOf('async function switchRole('), source.indexOf('async function loadBootstrap(')), ctx);
  return {state, events, fields, form, submitter,
    submit: () => ctx.submitInquiry({preventDefault() {}, target: form, submitter}),
    switchRole: () => ctx.switchRole({target: {value: 'buyer'}}),
    response: value => {response = value;}};
}

{
  const h = harness(); await h.submit(); await h.submit();
  const requests = h.events.filter(e => e.path);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].options.headers['Idempotency-Key'], requests[1].options.headers['Idempotency-Key']);
  assert.equal(requests[0].options.body, requests[1].options.body, 'unknown-outcome retry must use the same conversation/message identities');
  assert.ok(!h.events.filter(e => e.message).some(e => e.message.includes('private connection')));
  assert.equal(h.fields['#inquiry-text'].value, 'Please quote 100 cotton shirts.');
  h.fields['#inquiry-text'].value += ' Required within 30 days.'; await h.submit();
  const changed = h.events.filter(e => e.path).at(-1);
  assert.notEqual(changed.options.headers['Idempotency-Key'], requests[0].options.headers['Idempotency-Key']);
}
{
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); await h.submit();
  assert.equal(h.events.filter(e => e.path).length, 1, 'double activation must not create another inquiry');
  assert.equal(h.submitter.disabled, true);
  release({status: 'ok', action: 'pending_requirement_confirmation', project_id: 'case-1'});
  await pending;
  assert.equal(h.submitter.disabled, false);
}
{
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); h.state.session = {role: 'buyer'};
  release({status: 'ok', action: 'pending_email_approval', project_id: 'case-1', drafts_created: ['draft-1']});
  await pending;
  assert.equal(h.events.filter(e => e.kind).length, 0);
  assert.ok(!h.events.includes('reset') && !h.events.includes('refresh'));
  assert.equal(h.fields['#inquiry-result'].hidden, true);
}
{
  const h = harness(); let release;
  h.response(() => new Promise(resolve => {release = resolve;}));
  const pending = h.submit(); h.fields['#inquiry-text'].value = 'New unsent instructions.';
  release({status: 'ok', action: 'pending_email_approval', project_id: 'case-1', drafts_created: ['draft-1']});
  await pending;
  assert.equal(h.fields['#inquiry-text'].value, 'New unsent instructions.', 'a late accepted response must not erase newer input');
}
{
  const h = harness();
  const text = h.fields['#inquiry-text'].value;
  h.response(() => ({status: 'ok', action: 'pending_email_approval', project_id: 'case-1', drafts_created: ['draft-1']}));
  await h.submit();
  h.fields['#inquiry-text'].value = text;
  await h.submit();
  const requests = h.events.filter(e => e.path);
  assert.equal(requests.length, 2);
  assert.notEqual(requests[0].options.headers['Idempotency-Key'], requests[1].options.headers['Idempotency-Key'],
    'a deliberately repeated inquiry after confirmed acceptance must receive a new identity');
  assert.notEqual(requests[0].options.body, requests[1].options.body);
}
{
  const h = harness(); const releases = [];
  h.response(() => new Promise(resolve => releases.push(resolve)));
  const old = h.submit(); h.state.session = {role: 'buyer'};
  const current = h.submit();
  assert.equal(releases.length, 2, 'a new session must not wait for a hung previous-session fetch');
  releases[0]({status: 'ok', action: 'pending_email_approval', project_id: 'old-case', drafts_created: ['old-draft']});
  await old;
  assert.equal(h.submitter.disabled, true, 'old finally must not release the new session submit guard');
  assert.equal(h.events.filter(e => e.kind).length, 0);
  releases[1]({status: 'ok', action: 'pending_email_approval', project_id: 'new-case', drafts_created: ['new-draft']});
  await current;
  assert.equal(h.submitter.disabled, false);
  assert.ok(!h.fields['#inquiry-result'].textContent.includes('old-case'));
}
console.log('Inquiry unknown retries, fresh accepted submissions and controlled cross-session pending requests passed.');

{
  const h = harness(); const releases = [];
  h.response(() => new Promise(resolve => releases.push(resolve)));
  const previous = h.submit();
  assert.equal(h.submitter.disabled, true);
  await h.switchRole();
  assert.equal(h.submitter.disabled, false,
    'the actual role transition must release the native disabled button, not only allow programmatic submits');
  assert.equal(h.form.inquirySubmitting, false);
  assert.equal(h.state.inquiryAttempt, null);
  const next = h.submit();
  releases[0]({status: 'ok', action: 'pending_email_approval', project_id: 'previous', drafts_created: ['old']});
  await previous;
  assert.equal(h.submitter.disabled, true, 'stale finally cannot unlock the new request');
  releases[1]({status: 'ok', action: 'pending_email_approval', project_id: 'current', drafts_created: ['new']});
  await next;
  assert.equal(h.submitter.disabled, false);
}
console.log('Real role-handler transition releases native controls while preserving stale-request isolation.');
