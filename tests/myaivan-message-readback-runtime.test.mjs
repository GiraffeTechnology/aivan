import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('function savedMessageRow(');
assert.ok(start >= 0, 'Saved conversation renderer must exist');
const context = vm.createContext({
  escapeHtml: value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char])),
  roleLabel: value => value,
  formatTime: value => value,
});
vm.runInContext(source.slice(start, source.indexOf('async function openCase(', start)), context);
const message = {actor_role:'buyer', created_at:'2026-10-03', body_resolution:'resolved', canonical_language:'en', message_text:'Quoted <img src=x onerror=alert(1)>\nSecond line'};
const rendered = context.savedMessageRow(message);
assert.ok(rendered.includes('&lt;img'));
assert.ok(!rendered.includes('<img'));
assert.ok(rendered.includes('Second line'));
for (const patch of [
  {body_resolution:'missing_legacy_content'},
  {body_resolution:'integrity_mismatch'},
  {body_resolution:'unknown'},
  {canonical_language:'fr'},
  {canonical_language:null},
  {message_text:null},
  {message_text:{body:'not text'}},
]) {
  const html = context.savedMessageRow({...message, ...patch});
  assert.ok(!html.includes('Quoted'), JSON.stringify(patch));
  assert.match(html, /unavailable/i);
}
assert.match(context.savedMessageRow({...message, body_resolution:'integrity_mismatch'}), /integrity check failed/i);
assert.match(context.savedMessageRow({...message, body_resolution:'missing_legacy_content'}), /legacy record/i);
assert.ok(source.includes("section('Saved conversation', payload.messages, savedMessageRow)"));
assert.ok(!source.includes("section(t('消息证据（仅摘要）')"));
console.log('Saved conversation canonical body, legacy, integrity and escaped-text checks passed (local only).');
