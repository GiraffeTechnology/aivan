// Load the real emitted binding/context boundary for source-extracted host tests.
// Only the React DOM mount is synthetic; these are Node unit tests, not UI QA.
import fs from 'node:fs';
import vm from 'node:vm';

const root = new URL('../src/aivan/app/static/', import.meta.url);
const read = name => fs.readFileSync(new URL(name, root), 'utf8');
const manifest = JSON.parse(read('r6-execution-assets.json'));
const bundle = Object.keys(manifest.assets).find(name => name.endsWith('.js'));

export function attachR6HostVm(context) {
  Object.assign(context, {AbortController, AbortSignal, DOMException, URL, setTimeout, clearTimeout});
  vm.runInContext(read(bundle), context);
  const bindExecutionHost = context.myAivanR6Execution.bindExecutionHost;
  const updates = [];
  context.window.myAivanR6Execution = {
    bindExecutionHost,
    mountExecutionHost: () => ({update: value => updates.push(value), logout() {}, unmount() {}}),
  };
  vm.runInContext(read('execution-host-context.js'), context);
  vm.runInContext(read('r6-execution-host.js'), context);
  return {updates};
}
