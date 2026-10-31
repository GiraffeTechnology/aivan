#!/usr/bin/env node
'use strict';
/**
 * Five independent real-browser MyAivan first-UI sequences.
 * Uses installed loopback services and synthetic records only. No route mocking,
 * browser-state substitution, direct SQL writes, or external delivery.
 * Example: node scripts/verify_installed_first_ui.cjs --prefix INSTALL_DIR
 *   --package CANDIDATE.run --evidence OUTPUT --browser CHROME
 *   --supplier-id EXISTING_SYNTHETIC_SUPPLIER --synthetic-only
 *   --allow-local-restarts --run-id ui001
 * Without browser clipboard permission, --manual-copy-diagnostic --runs 1
 * verifies the real keyboard fallback and collects independent failures. It
 * cannot report automatic-copy acceptance or five consecutive passes, and it
 * never changes browser permissions or substitutes clipboard implementations.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const http = require('node:http');
const assert = require('node:assert/strict');
const {promisify} = require('node:util');
const {execFile} = require('node:child_process');
const execute = promisify(execFile);
const {chromium} = require('../integrations/openclaw-aivan-plugin/node_modules/playwright-core');
const privateLiterals = new Set();
function errorText(error) {
  let message = String(error?.message || error);
  for (const value of privateLiterals) message = message.split(value).join('[REDACTED]');
  return message.slice(0, 2000);
}

function argumentsFrom(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i++) {
    assert.ok(argv[i].startsWith('--'), 'Unexpected positional argument');
    const name = argv[i].slice(2);
    if (['synthetic-only', 'allow-local-restarts', 'manual-copy-diagnostic'].includes(name)) result[name] = true;
    else { assert.ok(argv[i + 1] && !argv[i + 1].startsWith('--'), 'Missing option value'); result[name] = argv[++i]; }
  }
  for (const name of ['prefix', 'package', 'evidence', 'browser', 'supplier-id', 'run-id'])
    assert.ok(result[name], 'Required option --' + name);
  assert.ok(result['synthetic-only'] && result['allow-local-restarts'],
    'Explicit synthetic-only and isolated local restart authorization required');
  assert.match(result['run-id'], /^[A-Za-z0-9_-]{1,24}$/);
  result.runs = Number(result.runs || 5);
  assert.equal(result.runs, result['manual-copy-diagnostic'] ? 1 : 5,
    'Acceptance requires five complete runs; manual-copy diagnosis requires --runs 1 and cannot pass acceptance');
  return result;
}
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const utc = () => new Date().toISOString();
const NAMES = [
  'Welcome renders', 'Start Working navigation', 'Three conversation areas',
  'User message right alignment', 'Aivan message left alignment',
  'Paste or keyboard fallback', 'File upload and readback', 'Image upload and preview',
  'Voice safely disabled', 'Generated draft review', 'Copy exact draft body',
  'Manual-send confirmation', 'Reject and regenerate', 'Explicit email approval',
  'Unavailable email copy fallback', 'Markdown backup', 'Truthful action audit',
  'No direct IM send', 'Trade workflow positioning', 'Digital trade assistant role',
];
const FIELDS = {
  category: 'apparel', product_type: 'cotton shirt', quantity: 1200,
  fabric_material: 'cotton', gsm: 180, color: 'white',
  size_ratio: 'S/M/L/XL 300/300/300/300', packaging: 'Individually bagged',
  destination: 'Tokyo', delivery_days: 60, incoterms: 'FOB',
};
const INQUIRY = 'RFQ: 1200 pcs white cotton shirts, 180 GSM, deliver to Tokyo within 60 days, FOB; sizes S/M/L/XL 300 each; individually bagged.';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGM0XhXKwMDAxMDAwMDAAAAOYAE2M0lPYwAAAABJRU5ErkJggg==', 'base64');

async function main() {
  const args = argumentsFrom(process.argv.slice(2));
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']) delete process.env[key];
  for (const key of ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS']) process.env[key] = '2';
  const prefix = path.resolve(args.prefix), output = path.resolve(args.evidence);
  fs.mkdirSync(output, {recursive: true, mode: 0o700});
  assert.ok(!fs.existsSync(path.join(output, 'results.json')), 'Use a new evidence directory; failures must be retained');
  const config = JSON.parse(fs.readFileSync(path.join(prefix, 'config.json'), 'utf8'));
  for (const value of [...Object.values(config.tenants || {}), ...Object.values(config.secrets || {})])
    if (typeof value === 'string' && value) privateLiterals.add(value);
  assert.ok(config.ports && Number.isInteger(config.ports.web), 'Installed web port is required');
  assert.ok(config.tenants && config.tenants['tenant-a'] && config.tenants['tenant-b'], 'Two isolated synthetic tenants required');
  assert.ok(!config.external || Object.keys(config.external).length === 0, 'External services are prohibited');
  assert.ok(!config.channels || (!config.channels.email_enabled && !config.channels.openclaw_url), 'Start with external channels disabled');
  const base = 'http://localhost:' + config.ports.web;
  const release = fs.realpathSync(path.join(prefix, 'current'));
  const releaseDirectory = fs.realpathSync(path.join(prefix, 'releases'));
  assert.equal(path.dirname(release), releaseDirectory, 'Installed current pointer must stay directly inside the real releases directory');
  const manifestPath = path.join(release, 'manifest.json');
  const manifestDigest = digest(fs.readFileSync(manifestPath));
  const packageBinding = await execute(path.join(release, 'runtime/bin/python3'), ['-B', '-I', '-c', `
import hashlib, sys, tarfile
with open(sys.argv[1], 'rb') as stream:
    for _ in range(100):
        if stream.readline() == b'__MYAIVAN_PAYLOAD__\\n':
            break
    else:
        raise ValueError('Not a recognized MyAivan package')
    with tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for member in archive:
            if member.name.removeprefix('./') == 'manifest.json' and member.isfile():
                print(hashlib.sha256(archive.extractfile(member).read()).hexdigest())
                break
        else:
            raise ValueError('The candidate package has no manifest')
`, path.resolve(args.package)], {timeout: 90000, maxBuffer: 4096});
  assert.equal(packageBinding.stdout.trim(), manifestDigest, 'Provided package differs from the installed candidate');
  const result = {
    evidence_class: args['manual-copy-diagnostic']
      ? 'one-run actual browser diagnosis; automatic clipboard acceptance remains unverified'
      : 'real installed-browser and authenticated API execution with synthetic inputs',
    production_acceptance: false, real_email_delivery: false, external_messages_sent: 0,
    started_at: utc(), package_sha256: digest(fs.readFileSync(args.package)),
    manifest_sha256: manifestDigest, package_manifest_matches_installation: true,
    runner_sha256: digest(fs.readFileSync(__filename)),
    run_id: args['run-id'], status: 'running', consecutive_passes: 0, runs: [],
    limitations: ['Email transport terminates only at a labelled synthetic loopback recorder.',
      'Clarification, synthetic supplier-reply setup, and post-rejection regeneration use real authenticated APIs and are labelled separately from browser actions.'],
  };
  const flush = () => fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(result, null, 2) + '\n', {mode: 0o600});
  flush();
  const messages = [];
  const server = http.createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/messages/send') { res.writeHead(404); res.end(); return; }
    let chunks = [], total = 0;
    req.on('data', value => { total += value.length; if (total > 1024 * 1024) req.destroy(); else chunks.push(value); });
    req.on('end', () => {
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        assert.equal(body.target_peer_id, 'synthetic-buyer@example.invalid', 'Only synthetic local recipient allowed');
        assert.ok(['email', 'smtp'].includes(body.channel), 'Direct IM transport prohibited');
        messages.push({channel: body.channel, recipient: body.target_peer_id,
          body_sha256: digest(Buffer.from(body.message_text)), recorded_at: utc()});
        const response = JSON.stringify({success: true, message_id: 'synthetic-browser-' + messages.length, sent_at: utc()});
        res.writeHead(200, {'Content-Type': 'application/json'}); res.end(response);
      } catch (_) { messages.push({unexpected_transport: true, recorded_at: utc()}); res.writeHead(400); res.end('{}'); }
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const recorder = 'http://127.0.0.1:' + server.address().port;
  let emailEnabled = false, browser, context, page, currentRun, currentCase;
  async function configureEmail(enabled) {
    // The event loop must remain available while the service uses the recorder.
    if (enabled) emailEnabled = true; // Also clean up a partially applied configuration on failure.
    await execute(path.join(prefix, 'myaivan'), ['prepare', '--openclaw-url', enabled ? recorder : '',
      enabled ? '--enable-email' : '--disable-email', '--restart'], {timeout: 240000, maxBuffer: 1024 * 1024});
    emailEnabled = enabled;
  }
  async function login(ctx, tenant = 'tenant-a') {
    const p = await ctx.newPage();
    p.setDefaultTimeout(60000);
    await p.goto(base, {waitUntil: 'domcontentloaded'});
    await p.locator('#tenant-id').fill(tenant);
    await p.locator('#access-key').fill(config.tenants[tenant]);
    await p.locator('#login-form button[type=submit]').click();
    await p.locator('#view-welcome.active').waitFor({state: 'visible'});
    assert.equal(await p.locator('#role-select').inputValue(), 'admin', 'Installed synthetic operator must have the declared admin role');
    return p;
  }
  async function api(method, endpoint, body, extraHeaders) {
    return page.evaluate(async ({method, endpoint, body, extraHeaders}) => {
      // Call the application's real authenticated request helper; no overrides.
      return api(endpoint, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)}), headers: extraHeaders || {}});
    }, {method, endpoint, body, extraHeaders});
  }
  async function openCase(id) {
    await page.locator('[data-view=cases]').click();
    await page.locator('#refresh-cases').click();
    const card = page.locator('#view-cases .case-card[data-case-id="' + id + '"]');
    await card.waitFor({state: 'visible'});
    await card.click();
    await page.locator('#view-case-detail.active').waitFor({state: 'visible'});
    await page.locator('#case-detail-title').waitFor({state: 'visible'});
  }
  async function check(number, work) {
    currentCase = number;
    const row = currentRun.cases[number - 1]; row.started_at = utc(); row.status = 'running'; flush();
    try {
      row.evidence = await work() || {}; row.completed_at = utc();
      row.status = row.evidence.automatic_copy_unverified ? 'partially_verified' : 'passed'; flush();
    } catch (error) {
      if (!args['manual-copy-diagnostic']) throw error;
      row.status = 'failed'; row.completed_at = utc();
      row.error = {name: error.name, message: errorText(error)};
      row.error.screenshot = await screenshot('case-' + number + '-failure'); flush();
      // Only an explicitly non-acceptance diagnostic may continue independent
      // cases. Dismiss the failed transient view through its real Close button;
      // do not change saved draft/approval state to make later steps succeed.
      for (const selector of ['dialog.commercial-preview', '#manual-copy-dialog']) {
        const dialog = page.locator(selector);
        if (await dialog.isVisible()) await dialog.getByRole('button', {name: 'Close', exact: true}).click();
      }
    }
  }
  async function screenshot(name) {
    const file = path.join(output, currentRun.run_id + '-' + name + '.png');
    // Use a normal top-of-page browser position so sticky headers are not
    // captured halfway down a stitched full-page screenshot.
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.screenshot({path: file, fullPage: true, animations: 'disabled'});
    return path.basename(file);
  }
  async function clipboardThroughInput(expected) {
    await page.locator('[data-view=new-inquiry]').click();
    const input = page.locator('#inquiry-text');
    await input.focus(); await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.press('ControlOrMeta+V');
    assert.equal(await input.inputValue(), expected, 'Actual clipboard paste must equal the copied draft');
  }
  async function copyDraft(button, expected) {
    const dialog = page.locator('#manual-copy-dialog');
    const outcome = Promise.race([
      page.waitForResponse(r => /\/api\/workbench\/cases\/[^/]+\/drafts\/[^/]+\/copy$/.test(new URL(r.url()).pathname)
        && r.request().method() === 'POST').then(response => ({method: 'automatic_clipboard', response})).catch(() => null),
      dialog.waitFor({state: 'visible'}).then(() => ({method: 'manual_keyboard'})).catch(() => null),
    ]);
    await button.click();
    const observed = await outcome; assert.ok(observed, 'Copy did not produce an audit response or the manual fallback dialog');
    if (observed.method === 'manual_keyboard') {
      const field = dialog.locator('#manual-copy-text');
      assert.equal(await field.inputValue(), expected);
      assert.equal(await field.evaluate(n => n.selectionStart === 0 && n.selectionEnd === n.value.length), true);
      await page.keyboard.press('ControlOrMeta+C');
      await dialog.getByRole('button', {name: 'Close', exact: true}).click();
      await clipboardThroughInput(expected);
      assert.ok(args['manual-copy-diagnostic'], 'Manual keyboard copy verified, but automatic copy/audit remains unverified; use the explicitly labelled diagnostic mode to continue other checks');
      return 'manual_keyboard';
    }
    assert.equal(observed.response.status(), 200, 'Automatic copy audit must be verified');
    const receipt = await observed.response.json();
    assert.equal(receipt.status, 'copied'); assert.equal(receipt.delivery_claim, false);
    assert.ok(receipt.audit_id, 'Automatic copying requires its actual audit identity');
    await clipboardThroughInput(expected);
    return 'automatic_clipboard';
  }
  async function prepareQuote(channel, suffix) {
    const id = currentRun.run_id + '-' + suffix;
    const participant = 'ui-buyer-' + id;
    const created = await api('POST', '/api/rfq/create-from-event', {
      source: 'myaivan', channel, conversation_id: id, message_id: id + '-inquiry',
      sender_id: 'synthetic-buyer@example.invalid', sender_display_name: 'Synthetic UI buyer',
      message_text: INQUIRY,
    }, {'X-AIVAN-Participant-ID': participant, 'X-AIVAN-Participant-Role': 'buyer',
      'X-AIVAN-Participant-Conversation-Role': 'buyer_thread', 'Idempotency-Key': id + '-inquiry'});
    assert.equal(created.status, 'ok');
    const before = await api('GET', '/api/workbench/cases/' + created.project_id + '/requirement');
    await api('PATCH', '/api/workbench/cases/' + created.project_id + '/requirement',
      {expected_requirement_sha256: before.requirement_sha256, fields: FIELDS},
      {'Idempotency-Key': id + '-clarify'});
    const sendReply = async (messageSuffix) => api('POST', '/api/rfq/create-from-event', {
      source: 'myaivan', channel, project_id: created.project_id, conversation_id: id + '-supplier',
      message_id: id + '-' + messageSuffix, sender_id: args['supplier-id'],
      sender_display_name: 'Synthetic supplier',
      message_text: 'We quote unit price USD 8.50; MOQ 100 pcs; production lead time 30 days. These are synthetic acceptance quotation facts.',
    }, {'X-AIVAN-Participant-ID': args['supplier-id'], 'X-AIVAN-Participant-Role': 'supplier',
      'X-AIVAN-Participant-Conversation-Role': 'supplier_thread', 'Idempotency-Key': id + '-' + messageSuffix});
    const reply = await sendReply('reply');
    assert.equal(reply.action, 'buyer_options_ready'); assert.ok(reply.drafts_created.length);
    currentRun.preparations.push({case_id: created.project_id, channel, path: 'real authenticated inquiry, human clarification and supplier reply APIs'});
    flush();
    return {caseId: created.project_id, draftId: reply.drafts_created[0], sendReply};
  }
  async function openPreview(item, manual) {
    await openCase(item.caseId);
    await page.locator('#case-detail [data-action=approve][data-draft-id="' + item.draftId + '"]').click();
    const dialog = page.locator('dialog.commercial-preview');
    await dialog.waitFor({state: 'visible'});
    await dialog.locator('[data-preview=approve]').waitFor({state: 'visible'});
    await page.waitForFunction(() => {
      const b = document.querySelector('dialog.commercial-preview [data-preview=approve]');
      return b && !b.disabled;
    });
    const box = dialog.locator('[name=manual]');
    if (manual !== undefined && await box.isChecked() !== manual) {
      await box.setChecked(manual);
      await dialog.locator('[data-preview=render]').click();
      await page.waitForFunction(() => !document.querySelector('dialog.commercial-preview [data-preview=approve]').disabled);
    }
    return dialog;
  }
  async function approveFromDialog(dialog) {
    const response = page.waitForResponse(r => /\/api\/drafts\/[^/]+\/approve$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST');
    await dialog.locator('[data-preview=approve]').click();
    const r = await response; const body = await r.json();
    assert.equal(r.status(), 200, 'Actual draft approval response: ' + JSON.stringify(body)); return body;
  }
  try {
    const verified = await execute(path.join(prefix, 'myaivan'), ['verify'], {timeout: 240000, maxBuffer: 1024 * 1024});
    result.installed_inventory_verification = {command: 'myaivan verify', exit_code: 0,
      stdout_sha256: digest(Buffer.from(verified.stdout)), stderr_sha256: digest(Buffer.from(verified.stderr)),
      release_pointer_contained: true, completed_at: utc()};
    flush();
    browser = await chromium.launch({executablePath: path.resolve(args.browser), chromiumSandbox: true, headless: true, args: ['--disable-dev-shm-usage']});
    for (let sequence = 1; sequence <= args.runs; sequence++) {
      assert.equal(digest(fs.readFileSync(manifestPath)), manifestDigest, 'Installed candidate changed; restart acceptance sequence');
      currentRun = {sequence, run_id: args['run-id'] + '-' + sequence, started_at: utc(), status: 'running',
        preparations: [], cases: NAMES.map((name, index) => ({id: index + 1, name, status: 'not_run'}))};
      result.runs.push(currentRun); flush();
      context = await browser.newContext({acceptDownloads: true});
      page = await login(context);
      let mainCase, mainDraft, mainDraftBody, rejected, emailCase, fallbackCase;
      await check(1, async () => {
        assert.match(await page.locator('#welcome-title').innerText(), /Welcome back/);
        return {screenshot: await screenshot('welcome')};
      });
      await check(19, async () => {
        const body = await page.locator('#view-welcome').innerText();
        assert.match(body, /inquiry/i); assert.match(body, /draft/i); assert.match(body, /commercial decisions/i);
        return {visible_trade_context: true};
      });
      await check(20, async () => {
        assert.match(await page.locator('#view-welcome').innerText(), /digital trade assistant/i);
        return {digital_trade_assistant: true};
      });
      await check(2, async () => {
        await page.locator('#view-welcome [data-open-view=new-inquiry]').click();
        await page.locator('#view-new-inquiry.active').waitFor({state: 'visible'});
        assert.equal(new URL(page.url()).hash, '#new-inquiry');
        return {fragment: '#new-inquiry'};
      });
      await check(3, async () => {
        // Before submission the log is correctly empty and has zero height;
        // the visible labelled panel, rather than an empty content node, is
        // the initial conversation area required by the first-UI contract.
        for (const selector of ['section[aria-labelledby="conversation-title"]', '#outbound-review', '#inquiry-form'])
          assert.equal(await page.locator(selector).isVisible(), true, 'Required area is visible: ' + selector);
        assert.equal(await page.locator('#conversation-stream[role=log]').count(), 1);
        return {screenshot: await screenshot('conversation-areas')};
      });
      await check(6, async () => {
        await page.locator('#paste-inquiry').click();
        await page.waitForFunction(() => /Pasted into the input|Ctrl\+V or Cmd\+V/.test(
          document.querySelector('#input-status')?.textContent || ''));
        const text = await page.locator('#input-status').innerText();
        assert.match(text, /Pasted into the input|Ctrl\+V or Cmd\+V/);
        assert.equal(await page.locator('#inquiry-text').evaluate(el => el === document.activeElement), true);
        return {observed_message: text};
      });
      await check(9, async () => {
        const voice = page.getByRole('button', {name: 'Voice unavailable'});
        assert.equal(await voice.isDisabled(), true);
        assert.match(await voice.getAttribute('title'), /not available/);
        return {safely_disabled: true};
      });
      await page.locator('#buyer-id').fill('ui-buyer-' + currentRun.run_id);
      await page.locator('#buyer-name').fill('Synthetic browser buyer');
      await page.locator('#inquiry-text').fill(args.input || INQUIRY);
      const invokeResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/invoke' && r.request().method() === 'POST');
      await page.locator('#inquiry-form button[type=submit]').click();
      const invoke = await invokeResponse; assert.equal(invoke.status(), 200);
      const created = await invoke.json(); assert.equal(created.status, 'ok'); assert.ok(created.project_id);
      mainCase = created.project_id; currentRun.case_id = mainCase; flush();
      await page.locator('#conversation-stream .assistant-message').waitFor({state: 'visible'});
      await check(4, async () => {
        const el = page.locator('#conversation-stream .user-message');
        assert.equal(await el.evaluate(n => getComputedStyle(n).alignSelf), 'flex-end');
        assert.equal(await el.innerText(), args.input || INQUIRY); return {screenshot: await screenshot('aligned-conversation')};
      });
      await check(5, async () => {
        assert.equal(await page.locator('#conversation-stream .assistant-message').evaluate(n => getComputedStyle(n).alignSelf), 'flex-start');
        return {actual_application_response: true};
      });
      await check(10, async () => {
        await page.locator('#outbound-review-content .draft-card').first().waitFor({state: 'visible'});
        const data = await api('GET', '/api/workbench/cases/' + mainCase);
        const commercial = data.drafts.find(d => ['supplier', 'buyer'].includes(d.target_role)
          && d.status === 'pending_approval' && created.drafts_created.includes(d.draft_id));
        assert.ok(commercial, 'The actual inquiry must generate a saved counterparty draft, not only an internal operator summary');
        mainDraft = commercial.draft_id;
        const card = page.locator('#outbound-review-content .draft-card').filter({has: page.locator('[data-action=copy][data-draft-id="' + mainDraft + '"]')});
        await card.waitFor({state: 'visible'});
        mainDraftBody = await card.locator('[data-action=copy]').getAttribute('data-copy');
        assert.equal(data.drafts.find(d => d.draft_id === mainDraft).message_text, mainDraftBody);
        assert.equal(await card.locator('[data-action=reject]').innerText(), 'Reject', 'The default English review must not leak a source-language action label');
        return {case_id: mainCase, draft_id: mainDraft, screenshot: await screenshot('generated-draft')};
      });
      await check(11, async () => {
        const before = await api('GET', '/api/workbench/cases/' + mainCase);
        const method = await copyDraft(page.locator('#outbound-review-content [data-action=copy][data-draft-id="' + mainDraft + '"]'), mainDraftBody);
        const data = await api('GET', '/api/workbench/cases/' + mainCase);
        const copied = payload => payload.audit.filter(a => a.event_type === 'DRAFT_COPIED').map(a => a.audit_id);
        if (method === 'automatic_clipboard') assert.ok(copied(data).length > copied(before).length);
        else assert.deepEqual(copied(data), copied(before), 'Manual keyboard copy cannot be falsely recorded as observed automatic copy');
        return {clipboard_body_sha256: digest(Buffer.from(mainDraftBody)), method,
          automatic_copy_unverified: method !== 'automatic_clipboard', delivery_claim: false};
      });
      await openCase(mainCase);
      await check(7, async () => {
        const bytes = Buffer.from('Synthetic browser cotton shirt specification. Individually bagged white cotton shirts.');
        const sourceName = currentRun.run_id + '.txt';
        await page.locator('#case-attachments input[type=file]').setInputFiles({name: sourceName, mimeType: 'text/plain', buffer: bytes});
        const upload = page.waitForResponse(r => new URL(r.url()).pathname === '/api/workbench/cases/' + mainCase + '/attachments' && r.request().method() === 'POST');
        await page.locator('#case-attachments button[type=submit]').click();
        const uploaded = await upload; assert.equal(uploaded.status(), 200);
        const saved = await uploaded.json(); assert.equal(saved.readback_verified, true);
        assert.equal(saved.source_sha256, digest(bytes));
        assert.equal(saved.source_name_sha256, digest(Buffer.from(sourceName)));
        await page.locator('#case-attachments').getByText('Stored and read back: text/plain', {exact: false}).waitFor();
        const data = await api('GET', '/api/workbench/cases/' + mainCase + '/attachments');
        assert.equal(data.readback_verified, true);
        const item = data.items.find(v => v.attachment_id === saved.attachment_id); assert.ok(item);
        assert.equal(item.file_name, 'attachment-' + item.sha256.slice(0, 12) + '.txt');
        const storedName = page.locator('#case-attachments strong').filter({hasText: item.file_name});
        await storedName.waitFor(); assert.equal(await storedName.innerText(), item.file_name);
        const downloaded = await page.evaluate(async endpoint => {
          const response = await fetch(endpoint, {credentials: 'same-origin', redirect: 'error'});
          return {status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer()))};
        }, item.download_path);
        assert.equal(downloaded.status, 200); assert.equal(digest(Buffer.from(downloaded.bytes)), item.sha256);
        return {attachment_id: item.attachment_id, content_sha256: item.sha256};
      });
      await check(8, async () => {
        const sourceName = currentRun.run_id + '.png';
        await page.locator('#case-attachments input[type=file]').setInputFiles({name: sourceName, mimeType: 'image/png', buffer: PNG});
        const upload = page.waitForResponse(r => new URL(r.url()).pathname === '/api/workbench/cases/' + mainCase + '/attachments' && r.request().method() === 'POST');
        await page.locator('#case-attachments button[type=submit]').click();
        const uploaded = await upload; assert.equal(uploaded.status(), 200);
        const saved = await uploaded.json(); assert.equal(saved.readback_verified, true);
        assert.equal(saved.sha256, digest(PNG)); assert.equal(saved.source_sha256, digest(PNG));
        assert.equal(saved.source_name_sha256, digest(Buffer.from(sourceName)));
        assert.equal(saved.file_name, 'attachment-' + saved.sha256.slice(0, 12) + '.png');
        const card = page.locator('#case-attachments article').filter({hasText: saved.file_name});
        await card.getByRole('button', {name: 'Preview image'}).click();
        await page.waitForFunction(() => [...document.querySelectorAll('#case-attachments img')].some(n => n.complete && n.naturalWidth > 0));
        assert.match(await card.innerText(), /stored, not parsed/i);
        return {image_sha256: digest(PNG), screenshot: await screenshot('image-readback')};
      });
      await check(12, async () => {
        const dialog = await openPreview({caseId: mainCase, draftId: mainDraft}, true);
        const exactBody = await dialog.locator('[data-preview=body]').inputValue();
        const approved = await approveFromDialog(dialog);
        assert.equal(approved.relay_required, true); assert.equal(approved.status, 'approved_pending_send'); assert.equal(approved.sent, false);
        await dialog.locator('[data-preview=copy]').click();
        await page.waitForFunction(() => /Copied and recorded|Automatic copying is unavailable|Copied, but/.test(
          document.querySelector('dialog.commercial-preview [data-preview=status]')?.textContent || ''));
        const manualCopy = /Automatic copying is unavailable/.test(await dialog.locator('[data-preview=status]').innerText());
        if (manualCopy) {
          assert.ok(args['manual-copy-diagnostic'], 'Automatic approved-preview copy remains unverified');
          await page.keyboard.press('ControlOrMeta+C');
        }
        await dialog.locator('[data-preview=close]').click();
        await clipboardThroughInput(exactBody);
        await page.locator('[data-view=relay]').click();
        const form = page.locator('form.relay-confirm[data-draft-id="' + mainDraft + '"]');
        await form.locator('[name=receipt]').fill('synthetic-local-' + currentRun.run_id);
        const receiptResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/relay/' + mainDraft + '/confirm' && r.request().method() === 'POST');
        await form.locator('button[type=submit]').click();
        const receiptHttp = await receiptResponse; const receipt = await receiptHttp.json();
        assert.equal(receiptHttp.status(), 200, 'Actual relay response: ' + JSON.stringify(receipt));
        assert.equal(receipt.status, 'relayed'); assert.equal(receipt.receipt.draft_id, mainDraft);
        assert.equal(receipt.receipt.case_id, mainCase);
        assert.equal(receipt.receipt.receipt_reference, 'synthetic-local-' + currentRun.run_id);
        const draft = await api('GET', '/api/drafts/' + mainDraft);
        assert.equal(draft.status, 'relayed');
        return {draft_id: mainDraft, status: draft.status, external_send: false,
          copy_method: manualCopy ? 'manual_keyboard' : 'automatic_clipboard'};
      });
      await check(13, async () => {
        rejected = await prepareQuote('whatsapp', 'reject');
        await openCase(rejected.caseId);
        page.once('dialog', d => d.accept());
        const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/drafts/' + rejected.draftId + '/reject');
        await page.locator('#case-detail [data-action=reject][data-draft-id="' + rejected.draftId + '"]').click();
        assert.equal((await response).status(), 200);
        const draft = await api('GET', '/api/drafts/' + rejected.draftId); assert.equal(draft.status, 'rejected');
        const regenerated = await rejected.sendReply('revised-reply');
        assert.equal(regenerated.action, 'buyer_options_ready');
        assert.ok(regenerated.drafts_created.every(id => id !== rejected.draftId));
        await openCase(rejected.caseId);
        await page.locator('#case-detail [data-action=approve][data-draft-id="' + regenerated.drafts_created[0] + '"]').waitFor();
        return {rejected_draft_id: rejected.draftId, regenerated_draft_ids: regenerated.drafts_created,
          continuation: 'actual authenticated supplier-reply API after real browser rejection'};
      });
      await check(14, async () => {
        await configureEmail(true);
        const count = messages.length; emailCase = await prepareQuote('email', 'email');
        assert.equal(messages.length, count);
        let dialog = await openPreview(emailCase, false);
        assert.equal(messages.length, count, 'Preview must not send');
        await dialog.locator('[data-preview=close]').click();
        assert.equal(messages.length, count, 'Close must not send');
        dialog = await openPreview(emailCase, false);
        const body = await dialog.locator('[data-preview=body]').inputValue();
        const approved = await approveFromDialog(dialog);
        assert.equal(approved.sent, true); assert.equal(approved.status, 'sent');
        assert.equal(messages.length, count + 1);
        assert.equal(messages.at(-1).body_sha256, digest(Buffer.from(body)));
        assert.equal(messages.at(-1).recipient, 'synthetic-buyer@example.invalid');
        await dialog.locator('[data-preview=close]').click();
        return {case_id: emailCase.caseId, local_recorder_requests: 1, requests_before_approval: 0, real_email_delivery: false};
      });
      await check(18, async () => {
        const count = messages.length;
        for (const channel of ['line', 'whatsapp']) {
          const item = await prepareQuote(channel, channel);
          const dialog = await openPreview(item);
          assert.equal(await dialog.locator('[name=manual]').isChecked(), true);
          assert.equal(await dialog.locator('[name=manual]').isDisabled(), true);
          const approved = await approveFromDialog(dialog);
          assert.equal(approved.sent, false); assert.equal(approved.relay_required, true);
          await dialog.locator('[data-preview=close]').click();
        }
        assert.equal(messages.length, count, 'No non-email transport allowed');
        return {channels: ['line', 'whatsapp'], transport_attempts: 0};
      });
      await check(15, async () => {
        await configureEmail(false);
        const count = messages.length; fallbackCase = await prepareQuote('email', 'unconfigured');
        const dialog = await openPreview(fallbackCase, false);
        const approved = await approveFromDialog(dialog);
        assert.equal(approved.sent, false); assert.notEqual(approved.status, 'sent');
        await dialog.locator('[data-preview=status]').filter({hasText: /No delivery is confirmed|not confirmed/i}).waitFor();
        await dialog.locator('[data-preview=close]').click();
        await openCase(fallbackCase.caseId);
        const copy = page.locator('#case-detail [data-action=copy][data-draft-id="' + fallbackCase.draftId + '"]');
        const body = await copy.getAttribute('data-copy'); const method = await copyDraft(copy, body);
        assert.equal(messages.length, count);
        return {state: approved.status, manual_copy_verified: true, copy_method: method, delivery_claim: false};
      });
      await check(16, async () => {
        await openCase(mainCase);
        const downloadPromise = page.waitForEvent('download');
        await page.locator('#case-detail a[href$="export?format=markdown"]').click();
        const download = await downloadPromise;
        assert.match(download.suggestedFilename(), /\.md$/);
        const destination = path.join(output, currentRun.run_id + '-backup.md'); await download.saveAs(destination);
        const text = fs.readFileSync(destination, 'utf8');
        for (const term of [mainCase, 'Drafts', 'Audit', 'Attachments', 'Conversations']) assert.ok(text.includes(term));
        return {file: path.basename(destination), sha256: digest(Buffer.from(text))};
      });
      await check(17, async () => {
        const cases = await Promise.all([mainCase, rejected.caseId, emailCase.caseId, fallbackCase.caseId].map(id => api('GET', '/api/workbench/cases/' + id)));
        const events = cases.flatMap(c => c.audit.map(a => a.event_type));
        if (!args['manual-copy-diagnostic']) assert.ok(events.includes('DRAFT_COPIED'));
        assert.ok(events.includes('DRAFT_REJECTED'));
        assert.ok(events.includes('DRAFT_SENT')); assert.ok(events.includes('DRAFT_SEND_FAILED') || events.includes('DRAFT_DELIVERY_UNCONFIRMED'));
        assert.ok(cases[0].receipts.some(receipt => receipt.draft_id === mainDraft
          && receipt.receipt_reference === 'synthetic-local-' + currentRun.run_id));
        assert.equal((await api('GET', '/api/drafts/' + emailCase.draftId)).status, 'sent');
        assert.notEqual((await api('GET', '/api/drafts/' + fallbackCase.draftId)).status, 'sent');
        return {audit_event_types: [...new Set(events)].sort(), copy_send_reject_states_distinguished: true,
          automatic_copy_unverified: !!args['manual-copy-diagnostic'],
          manual_keyboard_copy_audit: args['manual-copy-diagnostic'] ? 'not observable by application; no fabricated audit asserted' : undefined};
      });
      // DB-backed switch/relogin/restart recovery, separate from the original twenty.
      await openCase(rejected.caseId); await openCase(mainCase);
      const beforeRestart = await api('GET', '/api/workbench/cases/' + mainCase);
      const attachmentsBefore = await api('GET', '/api/workbench/cases/' + mainCase + '/attachments');
      await execute(path.join(prefix, 'myaivan'), ['restart'], {timeout: 240000, maxBuffer: 1024 * 1024});
      await context.close(); context = await browser.newContext({acceptDownloads: true}); page = await login(context);
      const afterRestart = await api('GET', '/api/workbench/cases/' + mainCase);
      const attachmentsAfter = await api('GET', '/api/workbench/cases/' + mainCase + '/attachments');
      assert.equal(attachmentsAfter.readback_verified, true);
      assert.deepEqual(attachmentsAfter.items, attachmentsBefore.items, 'Provider attachment readback changed after restart');
      for (const key of ['drafts', 'receipts', 'messages', 'audit'])
        assert.deepEqual(afterRestart[key], beforeRestart[key], 'Restart readback changed ' + key);
      const other = await browser.newContext(); const otherPage = await login(other, 'tenant-b');
      const status = await otherPage.evaluate(async endpoint => (await fetch(endpoint, {credentials: 'same-origin'})).status,
        '/api/workbench/cases/' + mainCase);
      assert.equal(status, 404); await other.close();
      assert.ok(currentRun.cases.every(c => c.status === 'passed'
        || (args['manual-copy-diagnostic'] && ['partially_verified', 'failed'].includes(c.status))));
      assert.equal(digest(fs.readFileSync(manifestPath)), manifestDigest);
      currentRun.recovery = {conversation_switch: true, fresh_login: true, actual_service_restart: true, cross_tenant_rejected: true};
      currentRun.status = args['manual-copy-diagnostic'] ? 'diagnostic_completed' : 'passed';
      currentRun.completed_at = utc(); if (!args['manual-copy-diagnostic']) result.consecutive_passes++; flush();
      await context.close(); context = null; page = null;
    }
    result.status = args['manual-copy-diagnostic'] ? (currentRun.cases.some(c => c.status === 'failed')
      ? 'diagnostic_completed_with_failures' : 'diagnostic_completed_automatic_copy_unverified')
      : result.consecutive_passes === 5 ? 'passed' : 'failed_reset_required';
  } catch (error) {
    result.status = 'failed_reset_required'; result.consecutive_passes = 0;
    result.error = {name: error.name, message: errorText(error)};
    if (currentRun) {
      currentRun.status = 'failed'; currentRun.completed_at = utc();
      if (currentCase && currentRun.cases[currentCase - 1].status === 'running')
        currentRun.cases[currentCase - 1].status = 'failed';
      if (page) {
        try { result.error.screenshot = await screenshot('failure'); } catch (_) { /* The original failure remains authoritative. */ }
      }
    }
  } finally {
    if (emailEnabled) {
      try { await configureEmail(false); result.email_cleanup = 'disabled'; }
      catch (_) { result.email_cleanup = 'failed_requires_operator_attention'; result.status = 'failed_reset_required'; }
    }
    if (context) await context.close().catch(() => {});
    if (browser) await browser.close().catch(() => {});
    await new Promise(resolve => server.close(resolve));
    result.synthetic_recorder = messages; result.completed_at = utc(); flush();
  }
  console.log(JSON.stringify({status: result.status, consecutive_passes: result.consecutive_passes, evidence: path.join(output, 'results.json')}));
  process.exitCode = ['passed', 'diagnostic_completed_automatic_copy_unverified'].includes(result.status) ? 0 : 1;
}
main().catch(error => { console.error(error.name + ': ' + errorText(error)); process.exitCode = 1; });
