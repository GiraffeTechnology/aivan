import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const sourcePath = fileURLToPath(new URL('../src/aivan/app/static/app.js', import.meta.url));
const source = fs.readFileSync(sourcePath, 'utf8');
const validatorStart = source.indexOf('function inquirySubmissionOutcome');
const submitStart = source.indexOf('async function submitInquiry');
const submitEnd = source.indexOf('async function approveDraft');
assert.ok(validatorStart >= 0 && submitStart > validatorStart && submitEnd > submitStart);

const fields = {
  '#buyer-id': { value: 'buyer-1' },
  '#buyer-name': { value: 'Buyer One' },
  '#inquiry-text': { value: 'Please quote 100 shirts.' },
  '#inquiry-result': { hidden: false, textContent: 'stale success' },
};
const toasts = [];
let apiPayload;
let loadCasesCalls = 0;
let resetCalls = 0;

const context = vm.createContext({
  console,
  JSON,
  $: (selector) => fields[selector],
  requestId: (prefix) => `${prefix}-fixed`,
  t: (value) => value,
  toast: (message, kind) => toasts.push({ message, kind }),
  loadCases: async () => { loadCasesCalls += 1; },
  api: async (path) => {
    assert.equal(path, '/invoke');
    return apiPayload;
  },
});
vm.runInContext(source.slice(validatorStart, submitEnd), context, { filename: sourcePath });
const submitInquiry = vm.runInContext('submitInquiry', context);
const event = {
  preventDefault() {},
  target: { reset() { resetCalls += 1; } },
};

apiPayload = {
  status: 'error',
  project_id: 'must-not-count-as-created',
  error: { code: 'INVALID_INVOKE_PAYLOAD', message: 'unsafe remote detail' },
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'fail-soft error envelope must preserve the form');
assert.equal(loadCasesCalls, 0, 'fail-soft error envelope must not refresh cases');
assert.equal(fields['#inquiry-text'].value, 'Please quote 100 shirts.');
assert.equal(fields['#inquiry-result'].hidden, true, 'stale success result must be hidden');
assert.equal(toasts.at(-1).kind, 'error');
assert.equal(toasts.at(-1).message.includes('unsafe remote detail'), false);

apiPayload = {
  status: 'ok',
  action: 'recorded_no_rfq_created',
  project_id: 'case-accepted',
  user_control_message: 'No RFQ was created.',
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'accepted non-RFQ state must retain input for correction');
assert.equal(loadCasesCalls, 1, 'accepted case must become visible');
assert.equal(fields['#inquiry-result'].hidden, false);
assert.match(fields['#inquiry-result'].textContent, /No RFQ was created/);
assert.equal(toasts.at(-1).kind, 'info');
assert.equal(toasts.at(-1).message.includes('询盘草稿已生成'), false);

apiPayload = {
  status: 'ok',
  action: 'pending_requirement_confirmation',
  project_id: 'case-blocked',
  user_control_message: 'Confirm the missing requirement before continuing.',
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'blocked requirement state must retain input for correction');
assert.equal(loadCasesCalls, 2);
assert.equal(toasts.at(-1).kind, 'info');
assert.equal(toasts.at(-1).message.includes('询盘草稿已生成'), false);

apiPayload = {
  status: 'ok',
  action: 'pending_email_approval',
  project_id: '  project-123  ',
  user_control_message: 'Drafts are pending human approval.',
  drafts_created: [],
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'empty drafts must not clear the inquiry form');
assert.equal(loadCasesCalls, 3);
assert.equal(fields['#inquiry-result'].hidden, false);
assert.match(fields['#inquiry-result'].textContent, /project-123/);
assert.equal(toasts.at(-1).kind, 'info');
assert.equal(toasts.at(-1).message.includes('询盘草稿已生成'), false);
assert.equal(fields['#inquiry-result'].textContent.includes('pending human approval'), false);

apiPayload = {
  status: 'ok',
  action: 'pending_email_approval',
  project_id: 'project-without-drafts-field',
  user_control_message: 'Drafts are pending human approval.',
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'missing drafts field must not clear the inquiry form');
assert.equal(loadCasesCalls, 4);
assert.equal(toasts.at(-1).kind, 'info');
assert.equal(toasts.at(-1).message.includes('询盘草稿已生成'), false);
assert.equal(fields['#inquiry-result'].textContent.includes('pending human approval'), false);

apiPayload = {
  status: 'ok',
  action: 'pending_email_approval',
  project_id: 'project-with-invalid-draft-type',
  user_control_message: 'Drafts are pending human approval.',
  drafts_created: 'draft-123',
};
await submitInquiry(event);
assert.equal(resetCalls, 0, 'non-array drafts field must not clear the inquiry form');
assert.equal(loadCasesCalls, 5);
assert.equal(toasts.at(-1).kind, 'info');
assert.equal(toasts.at(-1).message.includes('询盘草稿已生成'), false);
assert.equal(fields['#inquiry-result'].textContent.includes('pending human approval'), false);

apiPayload = {
  status: 'ok',
  action: 'pending_email_approval',
  project_id: 'project-with-real-draft',
  user_control_message: 'Drafts are pending human approval.',
  drafts_created: ['draft-123'],
};
await submitInquiry(event);
assert.equal(resetCalls, 1);
assert.equal(loadCasesCalls, 6);
assert.equal(fields['#inquiry-result'].hidden, false);
assert.match(fields['#inquiry-result'].textContent, /project-with-real-draft/);
assert.equal(toasts.at(-1).kind, 'success');
assert.match(toasts.at(-1).message, /人工审批/);

apiPayload = { status: 'ok', action: 'pending_email_approval', reply_text: 'Missing project identity.' };
await submitInquiry(event);
assert.equal(resetCalls, 1, 'missing project identity must preserve the form');
assert.equal(loadCasesCalls, 6);
assert.equal(toasts.at(-1).kind, 'error');

// Exercise the real loadCases helper: ordinary case-list request failures are
// rendered locally and must not escape into submitInquiry's creation error path.
const loadCasesStart = source.indexOf('async function loadCases');
const renderMetricsStart = source.indexOf('function renderMetrics');
assert.ok(loadCasesStart >= 0 && renderMetricsStart > loadCasesStart);
const realFields = {
  '#buyer-id': { value: 'buyer-real-helper' },
  '#buyer-name': { value: 'Buyer Real Helper' },
  '#inquiry-text': { value: 'Please quote 100 shirts.' },
  '#inquiry-result': { hidden: false, textContent: 'stale result' },
  '#case-state-filter': { value: '' },
  '#case-list': { innerHTML: '' },
};
const realToasts = [];
let realResetCalls = 0;
let realCaseRefreshCalls = 0;
const realContext = vm.createContext({
  console,
  JSON,
  URLSearchParams,
  state: { offset: 0, limit: 25 },
  $: (selector) => realFields[selector],
  requestId: (prefix) => `${prefix}-real-helper`,
  t: (value) => value,
  ht: (value) => value,
  escapeHtml: (value) => String(value),
  toast: (message, kind) => realToasts.push({ message, kind }),
  api: async (path) => {
    if (path === '/invoke') {
      return {
        status: 'ok',
        action: 'pending_email_approval',
        project_id: 'project-real-helper',
        user_control_message: 'Drafts are pending human approval.',
        drafts_created: ['draft-real-helper'],
      };
    }
    if (path.startsWith('/api/workbench/cases?')) {
      realCaseRefreshCalls += 1;
      throw new Error('case list unavailable');
    }
    throw new Error(`unexpected API path: ${path}`);
  },
});
vm.runInContext(
  `${source.slice(loadCasesStart, renderMetricsStart)}\n${source.slice(validatorStart, submitEnd)}`,
  realContext,
  { filename: sourcePath },
);
const realSubmitInquiry = vm.runInContext('submitInquiry', realContext);
await realSubmitInquiry({
  preventDefault() {},
  target: { reset() { realResetCalls += 1; } },
});
assert.equal(realResetCalls, 1);
assert.equal(realCaseRefreshCalls, 1);
assert.equal(realFields['#inquiry-result'].hidden, false);
assert.match(realFields['#inquiry-result'].textContent, /project-real-helper/);
assert.match(realFields['#case-list'].innerHTML, /读取案例失败/);
assert.equal(realToasts.some(({ message }) => message.includes('创建失败')), false);
assert.equal(realToasts.at(-1).kind, 'success');

console.log('myAIVAN inquiry runtime: response classification regression passed');