import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../src/aivan/app/templates/index.html', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
assert.match(html, /id="view-welcome"/);
assert.match(html, /Welcome back\. What should your AIVAN handle today\?/);
assert.match(html, /data-open-view="new-inquiry"[^>]*>Start Working</);
assert.match(app, /recoverableViews\.includes\(requestedView\) \? requestedView : 'welcome'/);
assert.match(app.slice(app.indexOf('async function login'), app.indexOf('async function logout')), /setView\('welcome'\)/);

const active = new Set();
const views = ['welcome', 'new-inquiry', 'dashboard'].map(name => ({
  id: `view-${name}`,
  classList: { toggle(_class, enabled) { if (enabled) active.add(name); else active.delete(name); } },
}));
let fragment;
const context = vm.createContext({
  state: { selectedCase: null, caseRequestGeneration: 0 },
  $: () => null,
  $$: selector => selector === '.view' ? views : [],
  history: { replaceState(_state, _title, value) { fragment = value; } },
  window: { scrollTo() {} },
  invalidateCaseView() {}, loadCases() {}, loadRelay() {}, loadHealth() {},
});
vm.runInContext(app.slice(app.indexOf('function setView('), app.indexOf('function populateRoles(')), context);
context.setView('welcome');
assert.deepEqual([...active], ['welcome']);
context.setView('new-inquiry');
assert.deepEqual([...active], ['new-inquiry']);
assert.equal(fragment, '#new-inquiry');
console.log('Welcome navigation checks passed (local runtime, not browser acceptance).');

import test from 'node:test';

function fn(name) {
  const markers = [`async function ${name}(`, `function ${name}(`];
  const start = markers.map(x => app.indexOf(x)).find(x => x >= 0);
  if (start === undefined) return '';
  const ends = ['\nasync function ', '\nfunction '].map(x => app.indexOf(x, start + 1)).filter(x => x >= 0);
  return app.slice(start, Math.min(...ends, app.length));
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function payload(id) {
  return { case: { case_id:id, requirement:{}, customer_id:'synthetic-buyer' },
    messages:[], participants:[], drafts:[], approvals:[], receipts:[], events:[], audit:[] };
}
function setup() {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, { hidden:false, innerHTML:'', textContent:'',
      classList:{ toggle() {} } });
    return nodes.get(selector);
  };
  const requests = [];
  const mounts = [];
  const context = vm.createContext({
    console, Headers, JSON, URLSearchParams, location:{hash:'',pathname:'/',search:''}, $:node, $$:() => [],
    window:{ scrollTo() {}, myAivanAttachments:{ dispose() {}, mount(_node,id) { mounts.push(id); } } },
    history:{ replaceState() {} }, t:x => x, ht:x => x, escapeHtml:x => String(x ?? ''),
    roleLabel:x => x, stateLabel:x => x, emptyHtml:() => '', savedMessageRow:() => '', buyerOptionRow:() => '',
    draftRow:() => '', eventRow:() => '', section:() => '', formatTime:x => x,
    cookie:() => '', requestId:() => 'synthetic-request', loadCases() {}, loadRelay() {}, loadHealth() {}, loadExecutionAssociation:async()=>{},
    api:path => { const d=deferred(); requests.push({path,...d}); return d.promise; },
  });
  vm.runInContext(app.slice(0,app.indexOf('const $ =')),context);
  vm.runInContext([fn('invalidateCaseView'),fn('showLogin'),fn('showApp'),fn('setView'),fn('caseRevisionContext'),fn('caseRevisionForm'),fn('openCase')].join('\n'),context);
  const state=vm.runInContext('state',context);
  state.session={role:'auditor'};
  state.bootstrap={actor:{capabilities:[]}};
  return {context,state,node,requests,mounts};
}

test('login and view changes clear every local selector without iterating a single DOM node', () => {
  const x = setup();
  const inputs = [{value:'old-a'}, {value:'old-b'}];
  const statuses = [{textContent:'old-a'}, {textContent:'old-b'}];
  x.context.$ = selector => selector === '[data-text-input]' ? inputs
    : selector === '[data-local-text-status]' ? statuses : [];
  x.context.showLogin();
  assert.ok(inputs.every(input => input.value === ''));
  assert.ok(statuses.every(status => status.textContent === ''));
  inputs.forEach(input => { input.value = 'selected'; });
  statuses.forEach(status => { status.textContent = 'loaded'; });
  x.context.setView('new-inquiry');
  assert.ok(inputs.every(input => input.value === ''));
  assert.ok(statuses.every(status => status.textContent === ''));
});

// W13 exercises the actual web functions with controlled API outcomes, not live DB acceptance.
function revisionSetup() {
  const x=setup(); let sequence=0;
  x.state.bootstrap.actor.capabilities=['create_inquiry','approve_outbound'];
  x.context.requestId=prefix=>`${prefix}-${++sequence}`;
  x.context.window.confirm=()=>true;
  x.toasts=[]; x.context.toast=(message,kind)=>x.toasts.push({message,kind});
  x.calls=[];
  x.context.api=(path,options)=>{const d=deferred();x.calls.push({path,options,...d});return d.promise;};
  vm.runInContext([fn('caseRevisionContext'),fn('caseRevisionForm'),fn('escapeHtml'),fn('draftRow'),
    fn('inquirySubmissionOutcome'),fn('submitCaseRevision'),fn('rejectDraft')].join('\n'),x.context);
  const detail=payload('same-case'); detail.conversations=[{role:'buyer_thread',channel:'myaivan',
    external_conversation_id:'saved-buyer-thread'}]; detail.case.customer_display_name='Saved Buyer';
  x.state.selectedCase=detail;
  const field={value:'Revise quantity to 120 shirts.'},result={textContent:''},button={disabled:false};
  const form={dataset:{caseId:'same-case'},elements:{namedItem:()=>field},
    querySelector:s=>s==='.revision-result'?result:button};
  const event={target:form,submitter:button,preventDefault(){}};
  return {...x,detail,field,result,button,form,event};
}
const accepted=(drafts=['new-draft'])=>({status:'ok',project_id:'same-case',action:'pending_email_approval',drafts_created:drafts});
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('W13 renders a real revision form and wires its submit event',()=>{
  const x=revisionSetup();
  assert.match(x.context.caseRevisionForm(x.detail),/id="case-revision-form" data-case-id="same-case"/);
  assert.match(app,/event.target.id === 'case-revision-form'\) submitCaseRevision\(event\)/);
  assert.match(fn('openCase'),/caseRevisionForm\(payload\)/);
});
test('W13 form is absent without capability or actual customer identity',()=>{
  const x=revisionSetup();x.state.bootstrap.actor.capabilities=[];
  assert.equal(x.context.caseRevisionForm(x.detail),'');
  x.state.bootstrap.actor.capabilities=['create_inquiry'];delete x.detail.case.customer_id;
  assert.equal(x.context.caseRevisionForm(x.detail),'');
});
test('W13 case identity is HTML escaped, not executable form markup',()=>{
  const x=revisionSetup();x.detail.case.case_id='case"><img src=x onerror=alert(1)>';
  const html=x.context.caseRevisionForm(x.detail);
  assert.equal(html.includes('<img'),false);assert.match(html,/&quot;&gt;&lt;img/);
});
test('W13 submits explicit case and actual buyer/thread, never a new inquiry',async()=>{
  const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);
  assert.equal(x.calls.length,1);assert.equal(x.calls[0].path,'/invoke');
  const call=x.calls[0],body=JSON.parse(call.options.body);
  assert.equal(body.project_id,'same-case');assert.equal(body.sender_id,'synthetic-buyer');
  assert.equal(body.conversation_id,'saved-buyer-thread');
  assert.equal(call.options.headers['X-AIVAN-Participant-ID'],'synthetic-buyer');
  assert.equal(call.options.headers['Idempotency-Key'],body.message_id);
  call.resolve({status:'error'});await p;
});
test('W13 rejects stale form, missing identity and unavailable capability with zero API calls',async()=>{
  const x=revisionSetup();x.form.dataset.caseId='other-case';await x.context.submitCaseRevision(x.event);
  x.form.dataset.caseId='same-case';x.state.bootstrap.actor.capabilities=[];await x.context.submitCaseRevision(x.event);
  x.state.bootstrap.actor.capabilities=['create_inquiry'];delete x.detail.case.customer_id;await x.context.submitCaseRevision(x.event);
  assert.equal(x.calls.length,0);
});
test('W13 concurrent clicks share one pending request, not duplicate mutations',async()=>{
  const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);
  assert.equal(x.button.disabled,true);await x.context.submitCaseRevision(x.event);assert.equal(x.calls.length,1);
  x.calls[0].reject(new Error('synthetic unavailable'));await p;assert.equal(x.button.disabled,false);
});
test('W13 uncertain retry retains request identity; edited instructions create a new identity',async()=>{
  const x=revisionSetup();const a=x.context.submitCaseRevision(x.event);x.calls[0].reject(new Error('lost'));await a;
  const b=x.context.submitCaseRevision(x.event);x.calls[1].reject(new Error('lost'));await b;
  assert.equal(x.calls[0].options.body,x.calls[1].options.body);
  assert.equal(x.field.value,'Revise quantity to 120 shirts.');
  x.field.value='Revise quantity to 140 shirts.';
  const c=x.context.submitCaseRevision(x.event);x.calls[2].resolve({status:'error'});await c;
  assert.notEqual(x.calls[0].options.headers['Idempotency-Key'],x.calls[2].options.headers['Idempotency-Key']);
});
test('W13 does not claim success or navigate for wrong-case or fail-soft response',async()=>{
  for(const response of [{...accepted(),project_id:'different-case'},{status:'error',message:'private backend detail'}]) {
    const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);x.calls[0].resolve(response);await p;
    assert.equal(x.calls.length,1);assert.equal(x.toasts.at(-1).kind,'error');
    assert.equal(x.result.textContent.includes('private backend detail'),false);
    assert.equal(x.field.value,'Revise quantity to 120 shirts.');
  }
});
test('W13 dependency/clarification acceptance does not claim drafts were regenerated',async()=>{
  const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);
  x.calls[0].resolve({...accepted([]),action:'pending_requirement_confirmation'});await tick();
  assert.equal(x.toasts.at(-1).kind,'info');assert.match(x.toasts.at(-1).message,/regeneration is not confirmed/);
  assert.equal(x.calls[1].path,'/api/workbench/cases/same-case');x.calls[1].resolve(x.detail);await p;
});
test('W13 late revision after logout cannot restore details or show a success toast',async()=>{
  const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);x.state.session=null;
  x.context.invalidateCaseView();x.calls[0].resolve(accepted());await p;
  assert.equal(x.calls.length,1);assert.equal(x.toasts.length,0);assert.equal(x.state.selectedCase,null);
});
test('W13 late revision cannot navigate over a newly selected case',async()=>{
  const x=revisionSetup();const p=x.context.submitCaseRevision(x.event);
  x.state.selectedCase=payload('other');x.state.caseRequestGeneration++;
  x.calls[0].resolve(accepted());await p;
  assert.equal(x.state.selectedCase.case.case_id,'other');assert.equal(x.calls.length,1);
});
test('W13 reject action carries case identity even outside the detail panel',async()=>{
  const x=revisionSetup();const row=x.context.draftRow({draft_id:'old-draft',case_id:'same-case',status:'pending_approval'});
  assert.match(row,/data-action="reject" data-case-id="same-case"/);
  assert.match(app,/rejectDraft\(action.dataset.draftId, action.dataset.caseId\)/);
  x.state.selectedCase=null;const p=x.context.rejectDraft('old-draft','same-case');
  x.calls[0].resolve({draft_id:'old-draft',status:'rejected'});await tick();
  assert.equal(x.calls[1].path,'/api/workbench/cases/same-case');x.calls[1].resolve(x.detail);await p;
});
test('W13 late rejection cannot reopen a case after logout or case navigation',async()=>{
  const x=revisionSetup();const p=x.context.rejectDraft('old-draft','same-case');
  x.context.invalidateCaseView();x.calls[0].resolve({draft_id:'old-draft',status:'rejected'});await p;
  assert.equal(x.calls.length,1);assert.equal(x.toasts.length,0);
});
test('W13 controlled reject then revision reloads the same saved history for fresh review',async()=>{
  const x=revisionSetup();let p=x.context.rejectDraft('old-draft','same-case');
  x.calls[0].resolve({draft_id:'old-draft',status:'rejected'});await tick();
  x.detail.drafts=[{draft_id:'old-draft',case_id:'same-case',status:'rejected'}];
  x.calls[1].resolve(x.detail);await p;
  assert.match(x.node('#case-detail').innerHTML,/case-revision-form/);
  p=x.context.submitCaseRevision(x.event);x.calls[2].resolve(accepted());await tick();
  x.detail.drafts.push({draft_id:'new-draft',case_id:'same-case',status:'pending_approval'});
  x.calls[3].resolve(x.detail);await p;
  assert.equal(x.state.selectedCase.case.case_id,'same-case');
  assert.equal(x.state.selectedCase.drafts[0].status,'rejected');
  assert.equal(x.state.selectedCase.drafts[1].status,'pending_approval');
  assert.equal(x.calls.some(call=>/approve|send|relay|order-confirmation/.test(call.path)),false);
  assert.match(x.toasts.at(-1).message,/fresh human review/);
});


test('W13 actual delegated submit and reject clicks reach the same-case handlers',async()=>{
  const x=revisionSetup(),listeners=new Map();
  x.context.document={addEventListener:(name,listener)=>listeners.set(name,listener)};
  const start=app.indexOf("document.addEventListener('click', async (event) => {");
  vm.runInContext(app.slice(start,app.indexOf("$('#logout-button')",start)),x.context);
  x.form.id='case-revision-form';x.form.matches=()=>false;
  listeners.get('submit')(x.event);assert.equal(x.calls[0].path,'/invoke');
  x.calls[0].resolve({status:'error'});await tick();
  const action={dataset:{action:'reject',draftId:'old-draft',caseId:'same-case'}};
  const click=listeners.get('click')({target:{closest:selector=>selector==='[data-action]'?action:null}});
  assert.equal(x.calls[1].path,'/api/drafts/old-draft/reject');
  x.calls[1].resolve({draft_id:'old-draft',status:'rejected'});await tick();
  assert.equal(x.calls[2].path,'/api/workbench/cases/same-case');x.calls[2].resolve(x.detail);await click;
});
test('W13 empty or excessive instructions cannot issue a mutation',async()=>{
  const x=revisionSetup();
  for(const text of ['  ','x'.repeat(20001)]) {x.field.value=text;await x.context.submitCaseRevision(x.event);}
  assert.equal(x.calls.length,0);
});
test('W13 missing saved web thread uses a stable opaque thread with explicit case identity',async()=>{
  const x=revisionSetup();x.detail.conversations=[{role:'supplier_thread',channel:'myaivan',external_conversation_id:'wrong-role-thread'}];
  const a=x.context.submitCaseRevision(x.event);x.calls[0].reject(new Error('lost'));await a;
  const b=x.context.submitCaseRevision(x.event);x.calls[1].resolve({status:'error'});await b;
  const first=JSON.parse(x.calls[0].options.body),second=JSON.parse(x.calls[1].options.body);
  assert.equal(first.project_id,'same-case');assert.match(first.conversation_id,/^case-revision-conversation-/);
  assert.equal(first.conversation_id,second.conversation_id);assert.notEqual(first.conversation_id,'wrong-role-thread');
});
test('W13 canceled rejection and unconfirmed server response cannot imply success',async()=>{
  const x=revisionSetup();x.context.window.confirm=()=>false;
  await x.context.rejectDraft('old-draft','same-case');assert.equal(x.calls.length,0);
  x.context.window.confirm=()=>true;
  const p=x.context.rejectDraft('old-draft','same-case');x.calls[0].resolve({draft_id:'different',status:'rejected'});await p;
  assert.equal(x.calls.length,1);assert.equal(x.toasts.at(-1).kind,'error');
});
test('W13 rejected draft has no approve or reject action after refresh',()=>{
  const x=revisionSetup();const row=x.context.draftRow({draft_id:'old-draft',case_id:'same-case',status:'rejected'});
  assert.equal(row.includes('data-action="approve"'),false);assert.equal(row.includes('data-action="reject"'),false);
});
