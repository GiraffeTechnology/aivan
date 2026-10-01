import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const sourcePath = fileURLToPath(new URL('../src/aivan/app/static/i18n.js', import.meta.url));
const source = fs.readFileSync(sourcePath, 'utf8');
const match = source.match(/const en = (\{[\s\S]*?\r?\n  \});\r?\n  const zht/);
assert.ok(match, 'authoritative English mirror must remain statically discoverable');
const english = vm.runInNewContext(`(${match[1]})`);
const sourceMap = Object.fromEntries(Object.keys(english).map((key) => [
  key,
  `ui.${crypto.createHash('sha256').update(key).digest('hex').slice(0, 20)}`,
]));
const englishMessages = Object.fromEntries(Object.entries(sourceMap).map(([key, id]) => [id, english[key]]));
const catalogVersion = crypto.createHash('sha256')
  .update(JSON.stringify(Object.fromEntries(Object.entries(englishMessages).sort())))
  .digest('hex');
const oldCandidate = 'a'.repeat(40);
const newCandidate = 'b'.repeat(40);

const textNode = { nodeValue: '登录 myAIVAN' };
const domReady = [];
const storage = new Map([['myaivan.locale', 'zh']]);
const fetchLog = [];
const deferred = new Map();

function manifest(candidate) {
  return {
    schema_version: 'myaivan.ui-catalog.v1', locale: 'en', source_locale: 'en',
    catalog_version: catalogVersion, candidate_sha: candidate,
    messages: englishMessages, source_map: sourceMap,
  };
}

function generated(locale, candidate, prefix = locale.toUpperCase()) {
  return {
    schema_version: 'myaivan.ui-catalog.v1', locale, source_locale: 'en',
    catalog_version: catalogVersion, candidate_sha: candidate,
    provider: 'ctranslate2', model: 'opus-mt', backend: 'cpu',
    proofreader: { role: 'proofread-only', model: 'qwen3.5:9b' },
    messages: Object.fromEntries(Object.entries(englishMessages).map(([id, value]) => [id, `${prefix}:${value}`])),
  };
}

function response(payload, ok = true) {
  return { ok, async json() { return payload; } };
}

let activeCandidate = oldCandidate;
async function fetchMock(url, options = {}) {
  fetchLog.push({ url: String(url), cache: options.cache });
  const value = String(url);
  if (value.startsWith('/api/ui/catalogs/en')) {
    const requested = new URL(value, 'https://myaivan.test').searchParams.get('candidate');
    return response(manifest(requested || activeCandidate));
  }
  const locale = value.match(/catalogs\/(fr|es|de|ko|ja)/)?.[1];
  if (deferred.has(locale)) return deferred.get(locale).promise;
  const requested = new URL(value, 'https://myaivan.test').searchParams.get('candidate');
  return response(generated(locale, requested));
}

const document = {
  body: {}, documentElement: { lang: 'zh-CN' }, title: '',
  addEventListener(type, callback) { if (type === 'DOMContentLoaded') domReady.push(callback); },
  querySelectorAll() { return []; },
  createTreeWalker() {
    let used = false;
    return { currentNode: null, nextNode() { if (used) return false; used = true; this.currentNode = textNode; return true; } };
  },
};
const windowEvents = new Map();
const window = {
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  },
  addEventListener(type, callback) { windowEvents.set(type, callback); },
  dispatchEvent(event) { windowEvents.get(event.type)?.(event); },
};
class CustomEvent { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } }
class MutationObserver { observe() {} }

const context = vm.createContext({
  window, document, fetch: fetchMock, console, CustomEvent, MutationObserver,
  NodeFilter: { SHOW_TEXT: 4 }, Node: { ELEMENT_NODE: 1 }, encodeURIComponent,
});
vm.runInContext(source, context, { filename: sourcePath });
assert.equal(domReady.length, 1);
await domReady[0]();
await window.myAivanI18n.ready;
assert.equal(window.myAivanI18n.catalogVersion, catalogVersion);
assert.equal(window.myAivanI18n.candidateSha, oldCandidate);
assert.equal(fetchLog[0].url, '/api/ui/catalogs/en');
assert.equal(fetchLog[0].cache, 'no-store', 'English manifest must bypass stale candidate cache');

// Inquiry outcome copy is part of the canonical catalog rather than a
// Simplified-Chinese fallback. English and Traditional Chinese are local
// mirrors; generated locales consume the same stable message ids.
const inquiryOutcomeCopy = {
  '服务器未确认案例创建，请检查输入后重试。': 'The server did not confirm case creation. Check the input and try again.',
  '请求已受理，请按案例提示继续。': 'The request was accepted. Continue from the case guidance.',
  '询盘草稿已生成，等待人工审批': 'The inquiry draft was created and is awaiting human approval.',
};
window.myAivanI18n.setLocale('en');
for (const [sourceText, englishText] of Object.entries(inquiryOutcomeCopy)) {
  assert.equal(window.myAivanI18n.t(sourceText), englishText);
  assert.ok(sourceMap[sourceText], `${sourceText} must have a stable catalog id`);
}
window.myAivanI18n.setLocale('zht');
assert.equal(
  window.myAivanI18n.t('服务器未确认案例创建，请检查输入后重试。'),
  '伺服器未確認案例建立，請檢查輸入後重試。',
);
assert.equal(
  window.myAivanI18n.t('请求已受理，请按案例提示继续。'),
  '請求已受理，請依案例提示繼續。',
);
assert.equal(
  window.myAivanI18n.t('询盘草稿已生成，等待人工审批'),
  '詢盤草稿已建立，等待人工審批',
);

// First selection loads once, installs, and subsequent requests reuse the in-memory promise/catalog.
window.myAivanI18n.setLocale('fr');
const firstLoad = await window.myAivanI18n.ensureGeneratedCatalog('fr');
const firstError = window.myAivanI18n.catalogError('fr');
assert.equal(firstLoad, true, firstError);
assert.equal(await window.myAivanI18n.ensureGeneratedCatalog('fr'), true);
const frRequests = fetchLog.filter(({ url }) => url.includes('/catalogs/fr?'));
assert.equal(frRequests.length, 1, JSON.stringify(frRequests));
assert.equal(window.myAivanI18n.t('登录 myAIVAN'), 'FR:Sign in to myAIVAN');
assert.equal(
  window.myAivanI18n.t('询盘草稿已生成，等待人工审批'),
  'FR:The inquiry draft was created and is awaiting human approval.',
);
assert.equal(document.documentElement.lang, 'fr');

// A translated HTML-looking value remains text-node content; no HTML sink is used by i18n.apply.
const xssPayload = generated('es', oldCandidate, 'ES');
xssPayload.messages[sourceMap['登录 myAIVAN']] = '<img src=x onerror=alert(1)>';
assert.equal(window.myAivanI18n.installGeneratedCatalog('es', xssPayload), true);
window.myAivanI18n.setLocale('es');
await window.myAivanI18n.ensureGeneratedCatalog('es');
assert.equal(textNode.nodeValue, '<img src=x onerror=alert(1)>');

// A late response for an older selection may populate cache but cannot replace the active locale.
function defer() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
const frLate = defer();
const deFast = defer();
deferred.set('ja', frLate);
deferred.set('de', deFast);
window.myAivanI18n.setLocale('ja');
window.myAivanI18n.setLocale('de');
deFast.resolve(response(generated('de', oldCandidate, 'DE')));
await window.myAivanI18n.ensureGeneratedCatalog('de');
frLate.resolve(response(generated('ja', oldCandidate, 'JA')));
await Promise.resolve(); await Promise.resolve();
assert.equal(window.myAivanI18n.locale, 'de');
assert.equal(window.myAivanI18n.t('登录 myAIVAN'), 'DE:Sign in to myAIVAN');

// Deployment switch: bootstrap mismatch forces a no-store, candidate-bound manifest refresh.
activeCandidate = newCandidate;
await window.myAivanI18n.assertCandidate(newCandidate);
const refresh = fetchLog.find(({ url }) => url === `/api/ui/catalogs/en?candidate=${newCandidate}`);
assert.ok(refresh);
assert.equal(refresh.cache, 'no-store');
window.myAivanI18n.setLocale('ko');
await window.myAivanI18n.ensureGeneratedCatalog('ko');
assert.ok(fetchLog.some(({ url }) => url === `/api/ui/catalogs/ko?candidate=${newCandidate}`));

// Old-candidate catalog payloads fail closed after the switch.
assert.equal(window.myAivanI18n.installGeneratedCatalog('ja', generated('ja', oldCandidate)), false);

// Exercise the real i18n runtime together with the real inquiry outcome
// classifier. This prevents identity t() stubs from hiding catalog omissions.
for (const code of ['fr', 'es', 'de', 'ko', 'ja']) {
  assert.equal(window.myAivanI18n.installGeneratedCatalog(code, generated(code, newCandidate)), true);
}
const appSourcePath = fileURLToPath(new URL('../src/aivan/app/static/app.js', import.meta.url));
const appSource = fs.readFileSync(appSourcePath, 'utf8');
const outcomeStart = appSource.indexOf('function inquirySubmissionOutcome');
const inquiryStart = appSource.indexOf('async function submitInquiry');
const inquiryEnd = appSource.indexOf('async function approveDraft');
assert.ok(outcomeStart >= 0 && inquiryStart > outcomeStart && inquiryEnd > inquiryStart);
const inquiryRuntime = appSource.slice(outcomeStart, inquiryEnd);
const outcomeScenarios = [
  {
    payload: { status: 'error', project_id: 'ignored' },
    kind: 'error', reset: 0, hidden: true,
    message: () => `${window.myAivanI18n.t('创建失败：')}${window.myAivanI18n.t('服务器未确认案例创建，请检查输入后重试。')}`,
  },
  {
    payload: { status: 'ok', action: 'pending_requirement_confirmation', project_id: 'case-pending' },
    kind: 'info', reset: 0, hidden: false,
    message: () => window.myAivanI18n.t('请求已受理，请按案例提示继续。'),
  },
  {
    payload: { status: 'ok', action: 'pending_email_approval', project_id: 'case-empty', drafts_created: [] },
    kind: 'info', reset: 0, hidden: false,
    message: () => window.myAivanI18n.t('请求已受理，请按案例提示继续。'),
  },
  {
    payload: { status: 'ok', action: 'pending_email_approval', project_id: 'case-ready', drafts_created: ['draft-1'] },
    kind: 'success', reset: 1, hidden: false,
    message: () => window.myAivanI18n.t('询盘草稿已生成，等待人工审批'),
  },
  {
    payload: { status: 'ok', action: 'pending_email_approval', drafts_created: ['draft-1'] },
    kind: 'error', reset: 0, hidden: true,
    message: () => `${window.myAivanI18n.t('创建失败：')}${window.myAivanI18n.t('服务器未确认案例创建，请检查输入后重试。')}`,
  },
];

for (const code of ['en', 'zht', 'fr', 'es', 'de', 'ko', 'ja']) {
  window.myAivanI18n.setLocale(code);
  for (const sourceText of [...Object.keys(inquiryOutcomeCopy), '创建失败：']) {
    assert.notEqual(
      window.myAivanI18n.t(sourceText),
      sourceText,
      `${code} must not fall back to Simplified Chinese for ${sourceText}`,
    );
  }
  for (const scenario of outcomeScenarios) {
    const fields = {
      '#buyer-id': { value: 'buyer-i18n' },
      '#buyer-name': { value: 'Buyer I18n' },
      '#inquiry-text': { value: 'Please quote 100 shirts.' },
      '#inquiry-result': { hidden: false, textContent: 'stale' },
    };
    const toasts = [];
    let resetCalls = 0;
    let loadCasesCalls = 0;
    const inquiryContext = vm.createContext({
      console,
      JSON,
      $: (selector) => fields[selector],
      requestId: (prefix) => `${prefix}-i18n`,
      t: (value) => window.myAivanI18n.t(value),
      toast: (message, kind) => toasts.push({ message, kind }),
      loadCases: async () => { loadCasesCalls += 1; },
      api: async (path) => {
        assert.equal(path, '/invoke');
        return scenario.payload;
      },
    });
    vm.runInContext(inquiryRuntime, inquiryContext, { filename: appSourcePath });
    const submitInquiry = vm.runInContext('submitInquiry', inquiryContext);
    await submitInquiry({
      preventDefault() {},
      target: { reset() { resetCalls += 1; } },
    });
    assert.equal(toasts.at(-1).kind, scenario.kind, `${code} toast kind`);
    assert.equal(toasts.at(-1).message, scenario.message(), `${code} toast translation`);
    assert.equal(resetCalls, scenario.reset, `${code} reset count`);
    assert.equal(fields['#inquiry-result'].hidden, scenario.hidden, `${code} result visibility`);
    assert.equal(loadCasesCalls, scenario.hidden ? 0 : 1, `${code} case refresh count`);
  }
}

console.log('myAIVAN i18n runtime: catalog and 7-language inquiry outcome checks passed');


await import('./myaivan-inquiry-runtime.test.mjs');
