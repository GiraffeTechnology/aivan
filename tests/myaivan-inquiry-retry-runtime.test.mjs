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
  const submitter = {disabled: false};
  let response = () => {throw Error('private connection detail');};
  let sequence = 0;
  const ctx = vm.createContext({state, JSON,
    $: selector => fields[selector], requestId: prefix => `${prefix}-${++sequence}`,
    t: value => value, toast: (message, kind) => events.push({message, kind}),
    loadCases: async () => events.push('refresh'),
    api: async (path, options) => {events.push({path, options}); return response();},
  });
  vm.runInContext(source.slice(start, end), ctx);
  return {state, events, fields, form, submitter,
    submit: () => ctx.submitInquiry({preventDefault() {}, target: form, submitter}),
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
console.log('Inquiry unknown-outcome replay, changed input, duplicate submit and session/new-input races passed.');
