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

// First selection loads once, installs, and subsequent requests reuse the in-memory promise/catalog.
window.myAivanI18n.setLocale('fr');
const firstLoad = await window.myAivanI18n.ensureGeneratedCatalog('fr');
const firstError = window.myAivanI18n.catalogError('fr');
assert.equal(firstLoad, true, firstError);
assert.equal(await window.myAivanI18n.ensureGeneratedCatalog('fr'), true);
const frRequests = fetchLog.filter(({ url }) => url.includes('/catalogs/fr?'));
assert.equal(frRequests.length, 1, JSON.stringify(frRequests));
assert.equal(window.myAivanI18n.t('登录 myAIVAN'), 'FR:Sign in to myAIVAN');
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

console.log('myAIVAN i18n runtime: 16 assertions passed');
