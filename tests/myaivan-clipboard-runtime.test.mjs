import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('async function copyDraftText(');
assert.ok(start >= 0, 'Clipboard denial must have an explicit fallback');
const end = source.indexOf('async function showImpact(', start);
const notices = [];
const fields = { '#manual-copy-text': { value: '', focus() {}, select() {} },
  '#manual-copy-dialog': { showModal() { this.open = true; } } };
let reject = false;
let copied;
const context = vm.createContext({
  navigator: { clipboard: { async writeText(text) { if (reject) throw new Error('denied'); copied = text; } } },
  $: key => fields[key], toast: (text, kind) => notices.push({text, kind}),
});
vm.runInContext(source.slice(start, end), context);
assert.equal(await context.copyDraftText('Actual draft'), true);
assert.equal(copied, 'Actual draft');
reject = true;
assert.equal(await context.copyDraftText('<script>plain text</script>'), false);
assert.equal(fields['#manual-copy-text'].value, '<script>plain text</script>');
assert.equal(fields['#manual-copy-dialog'].open, true);
assert.equal(notices.at(-1).kind, 'info');
console.log('Clipboard success/denial tests passed; no persistence or delivery claim.');
