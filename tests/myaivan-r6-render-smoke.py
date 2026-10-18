"""Real Chromium DOM plus loopback synthetic HTTP; not deployed MySQL/UI acceptance.

Run only through the authorized non-Windows remote test entry. No package install,
existing browser profile, business service, credential, or chain access is used.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit


def main() -> int:
    if platform.system() != "Linux":
        raise RuntimeError("This product test must run on the authorized Linux server")
    browser = os.environ.get("R6_SMOKE_CHROMIUM") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not browser:
        for cache in (Path.home() / ".cache/ms-playwright",):
            browser = next((str(p) for p in cache.glob("chromium*/chrome-linux*/chrome") if p.is_file()), None)
            if browser:
                break
    if not browser:
        print(json.dumps({"status": "NOT_RUN", "reason": "Existing Chromium unavailable"}))
        return 2
    root = Path(__file__).resolve().parent.parent
    static = root / "src/aivan/app/static"
    manifest = json.loads((static / "r6-execution-assets.json").read_text())
    bundle = next(name for name in manifest["assets"] if name.endswith(".js"))
    css = next(name for name in manifest["assets"] if name.endswith(".css"))
    app = (static / "app.js").read_text()

    def selected(begin: str, end: str) -> str:
        start = app.index(begin)
        return app[start:app.index(end, start)]

    functions = selected("async function api(", "\nfunction showLogin(")
    functions += selected("async function loadExecutionAssociation(", "\nfunction draftRow(")
    functions += app[app.rindex("window.addEventListener('pagehide'"):]
    order = "11111111-1111-4111-8111-111111111111"
    project = "22222222-2222-4222-8222-222222222222"
    shipment = "33333333-3333-4333-8333-333333333333"
    event = "44444444-4444-4444-8444-444444444444"
    prefix = "/api/workbench/cases/case-smoke/execution"
    timestamp = "2026-10-19T00:00:00Z"
    counts: dict[str, int] = {}
    requests: list[str] = []
    association = {"schema_version": "aivan.execution-association.v1", "case_id": "case-smoke",
                   "status": "associated", "readback_verified": True, "execution_reads_available": True,
                   "execution_read_prefix": prefix, "execution_readiness": "not_checked",
                   "local_order_id": order, "local_project_id": project}
    fixtures = {
        prefix + "/order": {"id": order, "project_id": project, "status": "confirmed",
                            "created_at": timestamp, "order_number": "SYNTHETIC-R6-ORDER"},
        prefix + "/production": {"milestones": [{"id": event, "milestone_type": "sewing",
                                                  "status": "delayed", "notes": "Synthetic delay"}]},
        prefix + "/qc": [{"id": event, "order_id": order, "result": "fail",
                           "rework_required": True, "created_at": timestamp}],
        prefix + "/events": [{"id": event, "order_id": order, "tenant_id": project,
                               "event_type": "SYNTHETIC_DELAY", "payload": {"shipment_id": shipment},
                               "occurred_at": timestamp}],
        prefix + "/shipments/" + shipment: {
            "id": shipment, "order_id": order, "created_at": timestamp,
            "carrier": "Synthetic Carrier", "tracking_number": "SYNTHETIC-TRACKING",
            "tracking_events": [{"id": event, "event_type": "SYNTHETIC_DELIVERED",
                                 "occurred_at": timestamp, "location": "Synthetic depot",
                                 "description": "Carrier delivery is not buyer sign-off"}]},
    }
    script = """
const state = {session:{role:'admin'},authGeneration:1,executionHost:null,executionBinding:null};
const $ = selector => document.querySelector(selector);
const requestId = () => 'synthetic-render-view';
const cookie = () => '';
""" + functions + """
const checks = [];
const check = (condition, message) => {if (!condition) throw Error(message); checks.push(message);};
const root = document.getElementById('r6-execution-workspace');
async function until(predicate) {
  const end = Date.now() + 4000;
  while (!predicate()) {if (Date.now() > end) throw Error('DOM condition timed out'); await new Promise(r => setTimeout(r,20));}
}
(async () => {
  await loadExecutionAssociation('case-smoke', () => true);
  await until(() => ['SYNTHETIC-R6-ORDER','SYNTHETIC_DELAY','SYNTHETIC-TRACKING','SYNTHETIC_DELIVERED','Synthetic delay'].every(x => root.textContent.includes(x)));
  check(root.querySelectorAll('table').length === 4 && root.textContent.includes('fail') && root.textContent.includes('Buyer sign-off not recorded.'), 'real React workspace rendered all resource panels');
  const context = state.executionHost.source.snapshot().context;
  const pending = context.request('/api/execution-graph/orders/ORDER_ID', {method:'GET',signal:new AbortController().signal})
    .then(() => 'unexpected-success', error => error.name);
  await new Promise(r => setTimeout(r,30));
  state.executionHost.invalidate('context-changing');
  check(!root.textContent.includes('SYNTHETIC-R6-ORDER'), 'synchronous invalidation clears rendered private records');
  check(await pending === 'AbortError', 'native fetch is aborted on lifetime invalidation');
  await loadExecutionAssociation('case-smoke', () => true);
  await until(() => root.textContent.includes('Select a confirmed order'));
  check(state.executionHost.source.snapshot().context.orderId === null, 'unavailable association does not activate an order');
  await loadExecutionAssociation('case-smoke', () => true);
  await until(() => root.textContent.includes('Access denied.'));
  check(!root.textContent.includes('SYNTHETIC-R6-ORDER'), 'HTTP403 stays denied and does not retain old panels');
  await loadExecutionAssociation('case-smoke', () => true);
  check(state.executionHost.source.snapshot().context === null && $('#execution-association-status').textContent.includes('read failed'), 'foreign advertised prefix fails closed');
  window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted:false}));
  check(state.executionHost === null && state.executionBinding === null && root.childNodes.length === 0, 'real root and subscription release on unload');
  $('#r6-smoke-result').textContent = JSON.stringify({status:'PASS',checks});
})().catch(error => {$('#r6-smoke-result').textContent = JSON.stringify({status:'FAIL',checks,error:error.message,body:root.textContent});});
"""
    script = script.replace("ORDER_ID", order)
    page = ("<!doctype html><html><head><meta charset='utf-8'>"
            f'<link rel="stylesheet" href="/static/{css}"></head><body>'
            '<p id="execution-association-status"></p><div id="r6-execution-workspace"></div>'
            '<pre id="r6-smoke-result">PENDING</pre>'
            '<script src="/static/execution-host-context.js"></script>'
            f'<script src="/static/{bundle}"></script>'
            '<script src="/static/r6-execution-host.js"></script>'
            f"<script>{script}</script></body></html>").encode()
    allowed_static = {bundle, css, "execution-host-context.js", "r6-execution-host.js"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args) -> None:
            pass

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            requests.append(path)
            counts[path] = counts.get(path, 0) + 1
            status, content_type = 200, "application/json"
            if path == "/":
                raw, content_type = page, "text/html; charset=utf-8"
            elif path.startswith("/static/") and path.removeprefix("/static/") in allowed_static:
                raw = (static / path.removeprefix("/static/")).read_bytes()
                content_type = "text/css" if path.endswith(".css") else "application/javascript"
            elif path == "/api/workbench/cases/case-smoke/execution-association":
                value = dict(association)
                if counts[path] == 2:
                    value["execution_reads_available"] = False
                elif counts[path] == 4:
                    value["execution_read_prefix"] = "/api/workbench/cases/foreign/execution"
                raw = json.dumps(value).encode()
            elif path in fixtures:
                if path.endswith("/events") and counts[path] == 2:
                    time.sleep(1)
                if path.endswith("/order") and counts[path] > 1:
                    status, raw = 403, b'{"detail":"synthetic denial"}'
                else:
                    raw = json.dumps(fixtures[path]).encode()
            elif path == "/favicon.ico":
                status, raw = 204, b""
            else:
                status, raw = 404, b'{"detail":"outside fixture allowlist"}'
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected for the explicitly aborted synthetic event read.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if server.server_port in {443, 8443}:
        server.server_close()
        raise RuntimeError("Reserved port unexpectedly selected")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile = Path(tempfile.mkdtemp(prefix="r6-chromium-"))
    command = [browser, "--headless=new", "--no-sandbox", "--disable-gpu",
               "--disable-background-networking", "--disable-component-update", "--disable-sync",
               "--disable-extensions", "--no-first-run",
               "--host-resolver-rules=EXCLUDE 127.0.0.1, MAP * ~NOTFOUND",
               "--user-data-dir=" + str(profile), "--remote-debugging-address=127.0.0.1",
               "--remote-debugging-port=0", "about:blank"]
    cdp = profile / "render-cdp.mjs"
    cdp.write_text("""
const [endpoint,url] = process.argv.slice(2);
const socket = new WebSocket(endpoint);
await new Promise((resolve,reject) => {socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
let sequence=0; const waiting=new Map(); const exceptions=[];
socket.addEventListener('message', event => {
  const value=JSON.parse(event.data);
  if (value.id && waiting.has(value.id)) {const pending=waiting.get(value.id);waiting.delete(value.id);value.error?pending.reject(Error(JSON.stringify(value.error))):pending.resolve(value.result);}
  if(value.method==='Runtime.exceptionThrown') exceptions.push(value.params.exceptionDetails.text);
});
const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;waiting.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
await call('Page.enable'); await call('Runtime.enable'); await call('Page.navigate',{url});
let result; const end=Date.now()+15000;
while(Date.now()<end) {
  const value=await call('Runtime.evaluate',{expression:"document.getElementById('r6-smoke-result')?.textContent",returnByValue:true});
  const text=value.result?.value;
  if(text && text!=='PENDING') {result=JSON.parse(text);break;}
  await new Promise(resolve=>setTimeout(resolve,50));
}
if(!result) {
 const value=await call('Runtime.evaluate',{expression:'document.body?.innerText',returnByValue:true});
 result={status:'FAIL',error:'Browser result timed out',body:value.result?.value,exceptions};
}
console.log(JSON.stringify(result));socket.close();
""", encoding="utf-8")
    process = None
    log = (profile / "chromium.log").open("wb")
    try:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
        active = profile / "DevToolsActivePort"
        end = time.monotonic() + 10
        while not active.is_file() and time.monotonic() < end and process.poll() is None:
            time.sleep(0.05)
        if not active.is_file():
            raise RuntimeError("Owned Chromium did not expose its local debug endpoint")
        port = int(active.read_text().splitlines()[0])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
            pages = json.load(response)
        endpoint = next(item["webSocketDebuggerUrl"] for item in pages if item["type"] == "page")
        node = shutil.which("node")
        if not node:
            raise RuntimeError("Selected Node is unavailable for the local browser protocol")
        run = subprocess.run([node, str(cdp), endpoint, f"http://127.0.0.1:{server.server_port}/"],
                             capture_output=True, text=True, timeout=25, check=False)
        result = json.loads(run.stdout) if run.returncode == 0 else {"status": "FAIL", "error": "Browser protocol controller failed"}
        record = {"status": result.get("status"), "checks": result.get("checks", []),
                  "error": result.get("error"), "controller_exit": run.returncode,
                  "requests": requests, "result_sha256": hashlib.sha256(run.stdout.encode()).hexdigest(),
                  "stderr_present": bool(run.stderr), "database": "NONE_SYNTHETIC_HTTP_ONLY",
                  "business_services_or_chain_calls": False}
        if result.get("status") != "PASS":
            record["diagnostic"] = result
        print(json.dumps(record))
        return 0 if run.returncode == 0 and result.get("status") == "PASS" and len(result.get("checks", [])) == 7 else 1
    finally:
        # This is the process group created above, with a new synthetic profile.
        # Never enumerate or signal another browser, service, transaction or task.
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        log.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
