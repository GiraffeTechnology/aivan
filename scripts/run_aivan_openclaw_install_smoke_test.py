#!/usr/bin/env python3
"""
Install smoke test for the OpenClaw plugin → AIVAN integration.

Reproduces the install-time checks that OpenClaw Gateway performs when:
  openclaw plugins install integrations/openclaw-aivan-plugin

What this tests (offline, no running AIVAN required):
  - npm install completes cleanly
  - npm run build produces dist/index.js and dist/index.d.ts
  - npm run typecheck passes
  - npx tsc passes with zero errors
  - dist/index.js exports the register() entry point
  - package.json main/types/exports point to existing dist files
  - openclaw.plugin.json passes structural validation
  - openclaw CLI install (if available) passes with LIFECYCLE_TRACE

If the openclaw CLI is not installed, the openclaw-specific steps are skipped
gracefully. All npm/tsc steps always run.

Usage:
    # From repo root:
    python scripts/run_aivan_openclaw_install_smoke_test.py

    # Verbose (show full command output):
    python scripts/run_aivan_openclaw_install_smoke_test.py --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PLUGIN_DIR = ROOT / "integrations" / "openclaw-aivan-plugin"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

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
            print(f"    stdout: {result.stdout.strip()[:500]}")
        if result.stderr.strip():
            print(f"    stderr: {result.stderr.strip()[:500]}")
    return result


def openclaw_available() -> bool:
    return shutil.which("openclaw") is not None


# ── Pre-flight ─────────────────────────────────────────────────────────────────
section("Pre-flight checks")
check("Plugin directory exists", PLUGIN_DIR.is_dir(),
      f"expected: {PLUGIN_DIR}")
check("package.json present", (PLUGIN_DIR / "package.json").is_file())
check("openclaw.plugin.json present", (PLUGIN_DIR / "openclaw.plugin.json").is_file())
check("index.ts present", (PLUGIN_DIR / "index.ts").is_file())

# ── npm install ────────────────────────────────────────────────────────────────
section("npm install")
result = run(["npm", "install"])
check("npm install exits 0", result.returncode == 0,
      result.stderr.strip()[:300] if result.returncode != 0 else "")
check("node_modules created", (PLUGIN_DIR / "node_modules").is_dir())
check("typescript available in node_modules",
      (PLUGIN_DIR / "node_modules" / "typescript").is_dir())

# ── npm run build ──────────────────────────────────────────────────────────────
section("npm run build (tsc compile)")
result = run(["npm", "run", "build"])
check("npm run build exits 0", result.returncode == 0,
      result.stderr.strip()[:500] if result.returncode != 0 else "")
check("dist/index.js created", (PLUGIN_DIR / "dist" / "index.js").is_file())
check("dist/index.d.ts created", (PLUGIN_DIR / "dist" / "index.d.ts").is_file())

# ── npm run typecheck ──────────────────────────────────────────────────────────
section("npm run typecheck (tsc --noEmit)")
result = run(["npm", "run", "typecheck"])
check("npm run typecheck exits 0", result.returncode == 0,
      result.stderr.strip()[:500] if result.returncode != 0 else "")

# ── npx tsc direct ────────────────────────────────────────────────────────────
section("npx tsc (direct invocation)")
result = run(["npx", "tsc"])
check("npx tsc exits 0 with zero errors", result.returncode == 0,
      (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")

# ── dist output content ────────────────────────────────────────────────────────
section("Compiled output correctness")
dist_js = PLUGIN_DIR / "dist" / "index.js"
if dist_js.is_file():
    dist_text = dist_js.read_text()
    check("dist/index.js exports register function",
          "export function register" in dist_text)
    check("dist/index.js references forwardEvent",
          "forwardEvent" in dist_text)
    check("dist/index.js not empty", len(dist_text.strip()) > 100)
else:
    check("dist/index.js content checks skipped (file missing)", False)

# ── package.json runtime entry alignment ──────────────────────────────────────
section("package.json runtime entry alignment")
pkg = json.loads((PLUGIN_DIR / "package.json").read_text())
main_val = pkg.get("main", "")
types_val = pkg.get("types", "")

check('main points to ./dist/index.js', main_val == "./dist/index.js",
      f"got: {main_val!r}")
check('types points to ./dist/index.d.ts', types_val == "./dist/index.d.ts",
      f"got: {types_val!r}")

main_abs = (PLUGIN_DIR / main_val.lstrip("./")).resolve() if main_val else None
types_abs = (PLUGIN_DIR / types_val.lstrip("./")).resolve() if types_val else None
check("main target exists on disk", bool(main_abs and main_abs.is_file()),
      f"resolved: {main_abs}")
check("types target exists on disk", bool(types_abs and types_abs.is_file()),
      f"resolved: {types_abs}")

exports = pkg.get("exports", {})
dot = exports.get(".", {})
check('exports["."]["import"] == "./dist/index.js"',
      dot.get("import") == "./dist/index.js",
      f"got: {dot.get('import')!r}")
check('exports["."]["types"] == "./dist/index.d.ts"',
      dot.get("types") == "./dist/index.d.ts",
      f"got: {dot.get('types')!r}")

oc = pkg.get("openclaw", {})
exts = oc.get("extensions", [])
check("openclaw.extensions is path-string list (not object-array)",
      isinstance(exts, list) and all(isinstance(e, str) for e in exts),
      f"got: {exts}")
check("openclaw.extensions entry points to dist JS",
      any("dist" in e and e.endswith(".js") for e in exts) if isinstance(exts, list) else False,
      f"entries: {exts}")

# ── openclaw.plugin.json structural validation ─────────────────────────────────
section("openclaw.plugin.json structure")
manifest_path = PLUGIN_DIR / "openclaw.plugin.json"
if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text())
    check("id present", bool(manifest.get("id")))
    check("name present", bool(manifest.get("name")))
    check("description present", bool(manifest.get("description")))
    check("version present", bool(manifest.get("version")))
    check("configSchema present", "configSchema" in manifest)
    check("activation.onStartup is true",
          manifest.get("activation", {}).get("onStartup") is True)
else:
    check("openclaw.plugin.json exists", False)

# ── openclaw CLI checks (skipped gracefully if not installed) ─────────────────
section("OpenClaw CLI checks")
if not openclaw_available():
    skip("openclaw version check", "openclaw CLI not installed")
    skip("openclaw plugins validate --entry ./dist/index.js", "openclaw CLI not installed")
    skip("openclaw plugins install . --force", "openclaw CLI not installed")
else:
    result = run(["openclaw", "--version"])
    check("openclaw --version exits 0", result.returncode == 0,
          result.stderr.strip()[:200] if result.returncode != 0 else "")
    if result.returncode == 0:
        print(f"    version: {(result.stdout + result.stderr).strip()}")

    result = run(["openclaw", "plugins", "validate", "--entry", "./dist/index.js"])
    check("openclaw plugins validate exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:400] if result.returncode != 0 else "")

    result = run(["openclaw", "plugins", "build", "--entry", "./dist/index.js", "--check"])
    check("openclaw plugins build --check exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:400] if result.returncode != 0 else "")

    result = run(
        ["openclaw", "plugins", "install", str(PLUGIN_DIR), "--force"],
        env={"OPENCLAW_PLUGIN_LIFECYCLE_TRACE": "1"},
    )
    check("openclaw plugins install exits 0", result.returncode == 0,
          (result.stdout + result.stderr).strip()[:500] if result.returncode != 0 else "")

    result = run(["openclaw", "plugins", "inspect", "openclaw-aivan"])
    out = (result.stdout + result.stderr)
    check("openclaw plugins inspect shows Status: loaded",
          result.returncode == 0 and "Status: loaded" in out,
          out.strip()[:400] if "Status: loaded" not in out else "")

# ── Summary ────────────────────────────────────────────────────────────────────
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
    print("AIVAN OPENCLAW INSTALL SMOKE TEST: PASS")
    print("============================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true",
                        help="Show full command stdout/stderr")
    args = parser.parse_args()
    verbose = args.verbose
