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
  $$: selector => selector === '.view' ? views : [],
  history: { replaceState(_state, _title, value) { fragment = value; } },
  window: { scrollTo() {} },
  loadCases() {}, loadRelay() {}, loadHealth() {},
});
vm.runInContext(app.slice(app.indexOf('function setView('), app.indexOf('function populateRoles(')), context);
context.setView('welcome');
assert.deepEqual([...active], ['welcome']);
context.setView('new-inquiry');
assert.deepEqual([...active], ['new-inquiry']);
assert.equal(fragment, '#new-inquiry');
console.log('Welcome navigation checks passed (local runtime, not browser acceptance).');
