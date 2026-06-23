#!/usr/bin/env python3
"""
Gateway P0 acceptance test for the AIVAN OpenClaw plugin.

Proves that OpenClaw Gateway can discover, install, validate, inspect, and
call AIVAN end-to-end. Also verifies that project_id and role_context are
preserved through the handler for supplier-reply routing.

What this tests:
  1. npm install + build + typecheck pass
  2. openclaw plugins validate --entry ./dist/index.js passes
  3. openclaw plugins build --entry ./dist/index.js --check passes
  4. openclaw plugins install . --force succeeds
  5. openclaw plugins list --verbose shows openclaw-aivan enabled
  6. All candidate IDs are tested with openclaw plugins inspect --runtime --json
  7. Node.js handler invocation: registers, receives mock WeChat supplier event,
     forwards to AIVAN with project_id and role_context preserved
  8. Supplier-side event is NOT misclassified (project_id and role_context intact)

If the openclaw CLI is not installed, CLI steps are skipped gracefully but the
Node.js handler test always runs.

Usage:
    python scripts/run_aivan_openclaw_gateway_p0_test.py
    python scripts/run_aivan_openclaw_gateway_p0_test.py --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
PLUGIN_DIR = ROOT / "integrations" / "openclaw-aivan-plugin"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"
INFO = "\033[36mINFO\033[0m"

failures: list[str] = []
skipped: list[str] = []
verbose = False


def section(title: str) -> None:
    print(f"\n── {title}")


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {FAIL}  {msg}")
        failures.append(msg)


def info(label: str, value: str) -> None:
    print(f"  {INFO}  {label}: {value}")


def skip(label: str, reason: str = "") -> None:
    print(f"  {SKIP}  {label}" + (f" ({reason})" if reason else ""))
    skipped.append(label)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd,
        cwd=str(cwd or PLUGIN_DIR),
        capture_output=True,
        text=True,
        env=merged_env,
    )
    if verbose:
        if result.stdout.strip():
            print(f"    stdout: {result.stdout.strip()[:800]}")
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()[:800]}")
    return result


def openclaw_available() -> bool:
    return shutil.which("openclaw") is not None


def node_available() -> bool:
    return shutil.which("node") is not None


# ── Environment versions ────────────────────────────────────────────────────────
section("Environment versions")
if openclaw_available():
    r = run(["openclaw", "--version"])
    ver = (r.stdout + r.stderr).strip()
    info("OpenClaw version", ver)
else:
    info("OpenClaw", "not installed")

r = run(["node", "--version"], cwd=ROOT)
info("Node version", (r.stdout + r.stderr).strip())
r = run(["npm", "--version"], cwd=ROOT)
info("npm version", (r.stdout + r.stderr).strip())

# ── Pre-flight ──────────────────────────────────────────────────────────────────
section("Plugin directory pre-flight")
check("Plugin directory exists", PLUGIN_DIR.is_dir())
check("package.json present", (PLUGIN_DIR / "package.json").is_file())
check("openclaw.plugin.json present", (PLUGIN_DIR / "openclaw.plugin.json").is_file())
check("index.ts present", (PLUGIN_DIR / "index.ts").is_file())

pkg_path = PLUGIN_DIR / "package.json"
pkg: dict = {}
if pkg_path.is_file():
    pkg = json.loads(pkg_path.read_text())

info("Package name", pkg.get("name", "(missing)"))
info("Package version", pkg.get("version", "(missing)"))

manifest_path = PLUGIN_DIR / "openclaw.plugin.json"
manifest: dict = {}
if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text())

info("Manifest id", manifest.get("id", "(missing)"))
info("Manifest name", manifest.get("name", "(missing)"))

# ── npm install → build → typecheck ────────────────────────────────────────────
section("npm install")
result = run(["npm", "install"])
check("npm install exits 0", result.returncode == 0,
      result.stderr.strip()[:300] if result.returncode != 0 else "")

section("npm run build (tsc)")
result = run(["npm", "run", "build"])
check("npm run build exits 0", result.returncode == 0,
      (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")
check("dist/index.js created", (PLUGIN_DIR / "dist" / "index.js").is_file())
check("dist/index.d.ts created", (PLUGIN_DIR / "dist" / "index.d.ts").is_file())

section("npm run typecheck (tsc --noEmit)")
result = run(["npm", "run", "typecheck"])
check("npm run typecheck exits 0", result.returncode == 0,
      (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")

section("npx tsc (direct)")
result = run(["npx", "tsc"])
check("npx tsc exits 0", result.returncode == 0,
      (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")

# ── package.json entry alignment ────────────────────────────────────────────────
section("package.json runtime entry alignment")
main_val = pkg.get("main", "")
types_val = pkg.get("types", "")
check("main points to ./dist/index.js", main_val == "./dist/index.js", f"got: {main_val!r}")
check("types points to ./dist/index.d.ts", types_val == "./dist/index.d.ts", f"got: {types_val!r}")

main_abs = (PLUGIN_DIR / main_val.lstrip("./")).resolve() if main_val else None
types_abs = (PLUGIN_DIR / types_val.lstrip("./")).resolve() if types_val else None
check("main target exists on disk", bool(main_abs and main_abs.is_file()), f"resolved: {main_abs}")
check("types target exists on disk", bool(types_abs and types_abs.is_file()), f"resolved: {types_abs}")

exports = pkg.get("exports", {})
dot = exports.get(".", {})
check('exports["."]["import"] == "./dist/index.js"', dot.get("import") == "./dist/index.js")
check('exports["."]["types"] == "./dist/index.d.ts"', dot.get("types") == "./dist/index.d.ts")

# ── openclaw.plugin.json manifest checks ───────────────────────────────────────
section("openclaw.plugin.json manifest")
check("id present", bool(manifest.get("id")))
check('id is "openclaw-aivan"', manifest.get("id") == "openclaw-aivan")
check("configSchema present", "configSchema" in manifest)
check("configSchema has aivanBaseUrl",
      "aivanBaseUrl" in manifest.get("configSchema", {}).get("properties", {}))
check("activation.onStartup is true", manifest.get("activation", {}).get("onStartup") is True)
check("contracts.tools present (tool-plugin metadata synced)", "tools" in manifest.get("contracts", {}))

# ── OpenClaw CLI checks ─────────────────────────────────────────────────────────
section("OpenClaw CLI: plugins validate")
if not openclaw_available():
    skip("openclaw plugins validate", "openclaw CLI not installed")
else:
    result = run(["openclaw", "plugins", "validate", "--entry", "./dist/index.js"])
    check("openclaw plugins validate exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:400] if result.returncode != 0 else "")
    if result.returncode == 0:
        out = (result.stdout + result.stderr).strip()
        info("validate output", out)

section("OpenClaw CLI: plugins build --check")
if not openclaw_available():
    skip("openclaw plugins build --check", "openclaw CLI not installed")
else:
    result = run(["openclaw", "plugins", "build", "--entry", "./dist/index.js", "--check"])
    check("openclaw plugins build --check exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:400] if result.returncode != 0 else "")

section("OpenClaw CLI: plugins install")
if not openclaw_available():
    skip("openclaw plugins install . --force", "openclaw CLI not installed")
else:
    result = run(
        ["openclaw", "plugins", "install", str(PLUGIN_DIR), "--force"],
        env={"OPENCLAW_PLUGIN_LIFECYCLE_TRACE": "1"},
    )
    check("openclaw plugins install exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")
    out = result.stdout + result.stderr
    check("install output mentions openclaw-aivan", "openclaw-aivan" in out, out[:200])

section("OpenClaw CLI: plugins list")
if not openclaw_available():
    skip("openclaw plugins list --verbose", "openclaw CLI not installed")
else:
    result = run(["openclaw", "plugins", "list", "--verbose"])
    out = result.stdout + result.stderr
    check("openclaw plugins list exits 0", result.returncode == 0)
    check("openclaw-aivan shown as enabled in list",
          "openclaw-aivan" in out and "enabled" in out,
          "plugin not found in list output")
    if verbose:
        # Show the AIVAN section of the list
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "openclaw-aivan" in line or "AIVAN" in line:
                print(f"    {lines[max(0,i-1)]}")
                print(f"    {line}")
                for j in range(i+1, min(i+6, len(lines))):
                    print(f"    {lines[j]}")

section("OpenClaw CLI: plugins inspect (all candidate IDs)")
CANDIDATE_IDS = [
    "aivan",
    "openclaw-aivan",
    "openclaw-aivan-plugin",
    "@giraffetechnology/aivan-openclaw-plugin",
    "@giraffetechnology/openclaw-aivan",
]
registered_id: str | None = None
if not openclaw_available():
    skip("openclaw plugins inspect (all IDs)", "openclaw CLI not installed")
else:
    for cid in CANDIDATE_IDS:
        result = run(["openclaw", "plugins", "inspect", cid, "--runtime", "--json"])
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                status = data.get("plugin", {}).get("status", "?")
                print(f"  {PASS}  inspect {cid!r}: status={status}")
                if registered_id is None:
                    registered_id = cid
            except json.JSONDecodeError:
                print(f"  {PASS}  inspect {cid!r}: exit 0 (non-JSON output)")
                if registered_id is None:
                    registered_id = cid
        else:
            print(f"  {SKIP}  inspect {cid!r}: not found (exit {result.returncode})")

    check("At least one candidate ID inspects successfully",
          registered_id is not None,
          f"tried: {CANDIDATE_IDS}")
    if registered_id:
        info("Registered plugin ID", registered_id)

    # Confirm Status: loaded
    if registered_id:
        result = run(["openclaw", "plugins", "inspect", registered_id, "--runtime", "--json"])
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                plugin = data.get("plugin", {})
                check("Status: loaded", plugin.get("status") == "loaded",
                      f"got: {plugin.get('status')}")
                check("activated is true", plugin.get("activated") is True)
                check("diagnostics empty", plugin.get("diagnostics", []) == [],
                      f"diagnostics: {plugin.get('diagnostics')}")
            except json.JSONDecodeError:
                pass

# ── ID naming alignment summary ────────────────────────────────────────────────
section("ID naming alignment")
info("Package name (package.json)", pkg.get("name", "(missing)"))
info("Manifest ID (openclaw.plugin.json)", manifest.get("id", "(missing)"))
info("Gateway registry ID (openclaw plugins list)", registered_id or "unknown — CLI not run")
info("Inspect ID", registered_id or "unknown — CLI not run")

# ── Node.js handler invocation test ────────────────────────────────────────────
section("Gateway call simulation: Node.js handler invocation")
if not node_available():
    skip("Node.js handler invocation test", "node not installed")
else:
    dist_js = PLUGIN_DIR / "dist" / "index.js"
    if not dist_js.is_file():
        skip("Node.js handler invocation test", "dist/index.js not built")
    else:
        # Inline Node.js test script
        handler_test = textwrap.dedent(f"""
        import {{ createServer }} from 'node:http';
        import {{ register }} from '{dist_js}';

        const captured = [];
        const server = createServer((req, res) => {{
          let body = '';
          req.on('data', chunk => {{ body += chunk; }});
          req.on('end', () => {{
            const parsed = JSON.parse(body);
            captured.push({{ path: req.url, body: parsed }});
            res.writeHead(200, {{ 'Content-Type': 'application/json' }});
            res.end(JSON.stringify({{ accepted: true, project_id: parsed.project_id, action: 'queued' }}));
          }});
        }});

        server.listen(8765, '127.0.0.1', async () => {{
          process.env.AIVAN_BASE_URL = 'http://127.0.0.1:8765';

          let registeredHandler = null;
          const mockApi = {{
            registerInteractiveHandler: (reg) => {{ registeredHandler = reg; }}
          }};
          register(mockApi);

          if (!registeredHandler) {{
            console.log('RESULT:FAIL:registerInteractiveHandler not called');
            server.close(); process.exit(1);
          }}

          const ctx = {{
            message: {{ text: 'We can quote 10000 shirts, cotton poplin, lead time 21 days, MOQ 10000 pcs.' }},
            channel: 'wechat',
            senderId: 'supplier-weixin-001',
            conversationId: 'conv-project-001',
            peer: {{ id: 'supplier-weixin-001', name: 'Supplier Co.' }},
            metadata: {{
              project_id: 'test-project-001',
              role_context: {{ side: 'supplier', role: 'seller' }}
            }}
          }};

          await registeredHandler.handler(ctx);

          if (captured.length === 0) {{
            console.log('RESULT:FAIL:no request reached mock AIVAN server');
            server.close(); process.exit(1);
          }}

          const evt = captured[0].body;
          const checks = {{
            'source_is_openclaw':      evt.source === 'openclaw',
            'channel_is_wechat':       evt.channel === 'wechat',
            'project_id_preserved':    evt.project_id === 'test-project-001',
            'role_context_preserved':  JSON.stringify(evt.role_context) === JSON.stringify({{ side: 'supplier', role: 'seller' }}),
            'message_text_forwarded':  (evt.message_text || '').includes('10000 shirts'),
            'sender_id_forwarded':     evt.sender_id === 'supplier-weixin-001',
            'mode_is_auto':            evt.mode === 'auto',
          }};

          for (const [k, v] of Object.entries(checks)) {{
            console.log('CHECK:' + (v ? 'PASS' : 'FAIL') + ':' + k);
          }}
          console.log('EVENT:' + JSON.stringify(evt));

          server.close();
          const allPassed = Object.values(checks).every(Boolean);
          process.exit(allPassed ? 0 : 1);
        }});
        """).strip()

        result = subprocess.run(
            ["node", "--input-type=module"],
            input=handler_test,
            capture_output=True,
            text=True,
            env={**os.environ, "AIVAN_BASE_URL": "http://127.0.0.1:8765"},
        )

        if verbose:
            if result.stderr.strip():
                print(f"    stderr: {result.stderr.strip()[:500]}")

        output = result.stdout + result.stderr
        check("Node.js handler invocation exits 0", result.returncode == 0,
              result.stderr.strip()[:300] if result.returncode != 0 else "")

        for line in result.stdout.splitlines():
            if line.startswith("CHECK:"):
                _, status, label = line.split(":", 2)
                check(f"handler: {label.replace('_', ' ')}", status == "PASS")
            elif line.startswith("EVENT:"):
                try:
                    evt = json.loads(line[6:])
                    info("forwarded event project_id", str(evt.get("project_id")))
                    info("forwarded event role_context", str(evt.get("role_context")))
                    info("forwarded event channel", str(evt.get("channel")))
                    info("forwarded event mode", str(evt.get("mode")))
                except Exception:
                    pass
            elif line.startswith("RESULT:FAIL:"):
                check("handler invocation", False, line.split(":", 2)[2])

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print("── ID summary")
print(f"  Package name:          {pkg.get('name', '(missing)')}")
print(f"  Manifest ID:           {manifest.get('id', '(missing)')}")
print(f"  Gateway registry ID:   {registered_id or 'unknown'}")
print(f"  Inspect ID:            {registered_id or 'unknown'}")
print()
if failures:
    print(f"\033[31m{len(failures)} check(s) failed.\033[0m")
    if skipped:
        print(f"\033[33m{len(skipped)} check(s) skipped.\033[0m")
    sys.exit(1)
else:
    ok_msg = "All checks passed"
    if skipped:
        ok_msg += f" ({len(skipped)} skipped)"
    print(f"\033[32m{ok_msg}.\033[0m")
    print("\n============================================================")
    print("AIVAN OPENCLAW GATEWAY P0 TEST: PASS")
    print("============================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true",
                        help="Show full command stdout/stderr")
    args = parser.parse_args()
    verbose = args.verbose
