import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  addEventListener(event, handler) { this.events[event] = handler; }
}
const all = root => [root, ...root.children.flatMap(all)];
const source = fs.readFileSync(new URL('../src/aivan/app/static/attachments.js', import.meta.url), 'utf8');
const imageBytes = new Uint8Array([137,80,78,71]);
const sha = Buffer.from(await webcrypto.subtle.digest('SHA-256', imageBytes)).toString('hex');
let fetched = 0;
let revoked = 0;
const context = vm.createContext({
  window:{}, document:{createElement:tag => new Node(tag)}, crypto:webcrypto,
  AbortController, Uint8Array, btoa:value => Buffer.from(value, 'binary').toString('base64'),
  URL:{createObjectURL:()=>'blob:test', revokeObjectURL:()=>revoked++},
  fetch:async (path, options) => {
    fetched++; assert.equal(path, '/api/workbench/cases/c1/attachments/a1/content');
    assert.equal(options.credentials, 'same-origin'); assert.equal(options.redirect, 'error');
    return {ok:true, headers:{get:()=> 'image/png'}, blob:async()=> new Blob([imageBytes], {type:'image/png'})};
  },
});
vm.runInContext(source, context);
const ui = context.window.myAivanAttachments;
const file = {name:'test.png', type:'image/png', size:4, arrayBuffer:async()=>imageBytes.buffer};
assert.equal((await ui.fileBody(file)).sha256, sha);
for (const change of [{size:0}, {size:10485761}, {type:'text/html'}, {type:'text/plain',size:65537}]) await assert.rejects(ui.fileBody({...file,...change}), /INVALID_FILE/);
assert.throws(()=>ui.contentPath('c1',{attachment_id:'a1',download_path:'https://evil.test/a'}), /INVALID_DOWNLOAD_PATH/);
const item = {attachment_id:'a1',file_name:'<script>not markup</script>',download_path:'/api/workbench/cases/c1/attachments/a1/content',content_type:'image/png',size_bytes:4,sha256:sha};
const requests = [];
let fail = true;
const api = async (path, options) => {
  assert.equal(path,'/api/workbench/cases/c1/attachments');
  if (!options) return {items:[item],readback_verified:true};
  requests.push(options);
  if(fail) throw Object.assign(Error('private provider response'), {status:503});
  return {...item,readback_verified:true,processing_status:'stored_image_not_parsed'};
};
const root = new Node('section');
ui.mount(root,'c1',api);
await new Promise(resolve=>setImmediate(resolve));
assert.ok(all(root).some(node=>node.textContent === item.file_name));
const form = all(root).find(node=>node.tag === 'form');
const input = all(root).find(node=>node.tag === 'input'); input.files = [file];
await form.events.submit({preventDefault(){}});
assert.ok(!all(root).some(node=>node.textContent.includes('private provider')));
fail = false;
await form.events.submit({preventDefault(){}});
assert.equal(requests.length,2);
assert.equal(requests[0].headers['Idempotency-Key'],requests[1].headers['Idempotency-Key']);
assert.equal(JSON.parse(requests[1].body).sha256,sha);
const preview = all(root).find(node=>node.textContent === 'Preview image');
await preview.events.click();
assert.equal(fetched,1);
assert.ok(all(root).some(node=>node.tag === 'img' && node.src === 'blob:test'));
ui.dispose(); assert.equal(revoked,1);
const badRoot = new Node('section');
ui.mount(badRoot, 'c1', async()=>({items:[{...item,sha256:'0'.repeat(64)}],readback_verified:true}));
await new Promise(resolve=>setImmediate(resolve));
await all(badRoot).find(node=>node.textContent === 'Preview image').events.click();
assert.ok(!all(badRoot).some(node=>node.tag === 'img'));
assert.ok(all(badRoot).some(node=>node.textContent.includes('preview unavailable')));
const unverified = new Node('section');
ui.mount(unverified, 'c1', async()=>({items:[item],readback_verified:false}));
await new Promise(resolve=>setImmediate(resolve));
assert.ok(!all(unverified).some(node=>node.textContent === item.file_name));
assert.ok(all(unverified).some(node=>node.textContent.includes('could not be loaded')));
ui.mount(new Node('section'),null,()=>{throw Error('No-case must not call API');});
const app = fs.readFileSync(new URL('../src/aivan/app/static/app.js', import.meta.url),'utf8');
assert.ok(app.includes("headers.set('X-AIVAN-CSRF', state.csrf)"));
assert.ok(app.includes("myAivanAttachments?.mount($('#case-attachments'), item.case_id, api)"));
console.log('Attachment UI validation, readback, retry, authenticated preview and disposal checks passed (local only).');
