#!/usr/bin/env python3
"""
OpenClaw Gateway plugin install simulation for AIVAN.

Runs:
  OPENCLAW_PLUGIN_LIFECYCLE_TRACE=1 openclaw plugins install <plugin_dir> --force

Captures and reports:
  - Full stdout/stderr with lifecycle trace
  - Exit code
  - Detected plugin ID
  - Detected manifest ID
  - Detected package name
  - Install path
  - Exact failure reason if install fails

Usage:
    python scripts/run_aivan_openclaw_install_simulation.py
    python scripts/run_aivan_openclaw_install_simulation.py --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PLUGIN_DIR = ROOT / "integrations" / "openclaw-aivan-plugin"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"
INFO = "\033[36mINFO\033[0m"

verbose = False


def section(title: str) -> None:
    print(f"\n── {title}")


def info(label: str, value: str) -> None:
    print(f"  {INFO}  {label}: {value}")


def check(label: str, ok: bool, detail: str = "") -> None:
    tag = PASS if ok else FAIL
    msg = f"{label}" + (f": {detail}" if detail else "")
    print(f"  {tag}  {msg}")
    return ok


def openclaw_available() -> bool:
    return shutil.which("openclaw") is not None


# ── Pre-flight ──────────────────────────────────────────────────────────────────
section("Pre-flight")

if not openclaw_available():
    print(f"\n  {SKIP}  openclaw CLI not installed")
    print("\nSKIPPED_OPENCLAW_CLI_NOT_FOUND")
    print("\nNote: Run this script in an environment with OpenClaw Gateway installed.")
    print("      The plugin install, inspect, and validate steps require the openclaw CLI.")
    sys.exit(0)

pkg_path = PLUGIN_DIR / "package.json"
manifest_path = PLUGIN_DIR / "openclaw.plugin.json"
dist_js = PLUGIN_DIR / "dist" / "index.js"

pkg: dict = json.loads(pkg_path.read_text()) if pkg_path.is_file() else {}
manifest: dict = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}

info("Plugin directory", str(PLUGIN_DIR))
info("Package name", pkg.get("name", "(missing)"))
info("Package version", pkg.get("version", "(missing)"))
info("Manifest ID", manifest.get("id", "(missing)"))
info("dist/index.js exists", str(dist_js.is_file()))

r_ver = subprocess.run(["openclaw", "--version"], capture_output=True, text=True)
info("OpenClaw version", (r_ver.stdout + r_ver.stderr).strip())

# ── Run install with lifecycle trace ────────────────────────────────────────────
section("Running install simulation")
print(f"  Command: OPENCLAW_PLUGIN_LIFECYCLE_TRACE=1 openclaw plugins install {PLUGIN_DIR} --force")
print()

env = {**os.environ, "OPENCLAW_PLUGIN_LIFECYCLE_TRACE": "1"}
result = subprocess.run(
    ["openclaw", "plugins", "install", str(PLUGIN_DIR), "--force"],
    capture_output=True,
    text=True,
    env=env,
)

out_combined = result.stdout + result.stderr

# ── Parse output ────────────────────────────────────────────────────────────────
section("Install output analysis")

# Show full output if verbose, else show key lines
if verbose:
    print("  Full output:")
    for line in out_combined.splitlines():
        print(f"    {line}")
else:
    # Show only non-lifecycle-trace lines plus error lines
    key_lines = [
        line for line in out_combined.splitlines()
        if not line.startswith("[plugins:lifecycle]")
        or "status=error" in line
        or "error" in line.lower()
    ]
    if key_lines:
        print("  Key output lines:")
        for line in key_lines[:30]:
            print(f"    {line}")

# Extract lifecycle trace events
lifecycle_events = []
for line in out_combined.splitlines():
    if line.startswith("[plugins:lifecycle]"):
        lifecycle_events.append(line)

print()
info("Lifecycle events captured", str(len(lifecycle_events)))
info("Exit code", str(result.returncode))

# Check for errors in lifecycle trace
error_events = [e for e in lifecycle_events if "status=error" in e]
if error_events:
    print("\n  Lifecycle errors:")
    for e in error_events:
        print(f"    {e}")

# Detect plugin ID from output
detected_id: str | None = None
m = re.search(r"Installed plugin: (\S+)", out_combined)
if m:
    detected_id = m.group(1)
m2 = re.search(r'pluginId="([^"]+)"', out_combined)
if m2 and not detected_id:
    detected_id = m2.group(1)

# Detect install path
detected_install_path: str | None = None
m3 = re.search(r"Installing to ([^\n]+)", out_combined)
if m3:
    detected_install_path = m3.group(1).strip()

# ── Results ─────────────────────────────────────────────────────────────────────
section("Install results")
ok = check("openclaw plugins install exits 0", result.returncode == 0,
           out_combined.strip().splitlines()[-1][:300] if result.returncode != 0 else "")
info("Detected plugin ID", detected_id or "(not detected)")
info("Manifest ID", manifest.get("id", "(missing)"))
info("Package name", pkg.get("name", "(missing)"))
info("Install path", detected_install_path or "(not detected)")

# ID alignment check
if detected_id and manifest.get("id"):
    check("Detected ID matches manifest ID",
          detected_id == manifest["id"],
          f"detected={detected_id!r}, manifest={manifest['id']!r}")

# ── Post-install inspect ─────────────────────────────────────────────────────────
section("Post-install inspect")
if result.returncode != 0:
    print(f"  {SKIP}  Skipping inspect (install failed)")
else:
    inspect_id = detected_id or manifest.get("id", "openclaw-aivan")
    r_inspect = subprocess.run(
        ["openclaw", "plugins", "inspect", inspect_id, "--runtime", "--json"],
        capture_output=True, text=True,
    )
    check("openclaw plugins inspect exits 0", r_inspect.returncode == 0,
          (r_inspect.stdout + r_inspect.stderr).strip()[:200] if r_inspect.returncode != 0 else "")
    if r_inspect.returncode == 0:
        try:
            data = json.loads(r_inspect.stdout)
            plugin = data.get("plugin", {})
            check("Status: loaded", plugin.get("status") == "loaded",
                  f"got: {plugin.get('status')}")
            check("activated: true", plugin.get("activated") is True)
            diag = plugin.get("diagnostics", [])
            check("No diagnostics (zero errors)", diag == [], f"diagnostics: {diag}")
            info("Tool count", str(len(plugin.get("tools", []))))
            info("Hook count", str(plugin.get("hookCount", 0)))
            info("Config schema", "present" if plugin.get("configSchema") else "missing")
        except json.JSONDecodeError:
            check("inspect returns valid JSON", False, r_inspect.stdout[:200])

# ── Summary ─────────────────────────────────────────────────────────────────────
section("Install simulation summary")
print(f"  Package name:          {pkg.get('name', '(missing)')}")
print(f"  Manifest ID:           {manifest.get('id', '(missing)')}")
print(f"  Detected Gateway ID:   {detected_id or '(not detected)'}")
print(f"  Install path:          {detected_install_path or '(not detected)'}")
print(f"  Exit code:             {result.returncode}")
print(f"  Lifecycle events:      {len(lifecycle_events)}")
print(f"  Lifecycle errors:      {len(error_events)}")
print()

if result.returncode != 0:
    print(f"\033[31mInstall FAILED (exit code {result.returncode}).\033[0m")
    print("\nOriginal error:")
    # Show last non-lifecycle-trace lines as the error
    error_lines = [
        l for l in out_combined.splitlines()
        if not l.startswith("[plugins:lifecycle]")
    ]
    for l in error_lines[-10:]:
        print(f"  {l}")
    sys.exit(1)
else:
    print(f"\033[32mInstall PASSED.\033[0m")
    print("\n============================================================")
    print("AIVAN OPENCLAW INSTALL SIMULATION: PASS")
    print("============================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true",
                        help="Show full command stdout/stderr")
    args = parser.parse_args()
    verbose = args.verbose
