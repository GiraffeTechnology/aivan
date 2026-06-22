#!/usr/bin/env python3
"""Validate ClawHub plugin package metadata and structure for AIVAN.

Checks both the source structure and the installable package that
OpenClaw Gateway expects when running:
  openclaw plugins install integrations/openclaw-aivan-plugin
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PLUGIN_DIR = ROOT / "integrations" / "openclaw-aivan-plugin"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  {PASS}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {FAIL}  {msg}")
        failures.append(msg)


def section(title: str) -> None:
    print(f"\n── {title}")


# ── Plugin directory structure ─────────────────────────────────────────────────
section("Plugin directory structure")
check("integrations/openclaw-aivan-plugin/ exists", PLUGIN_DIR.is_dir())
check("package.json exists", (PLUGIN_DIR / "package.json").is_file())
check("openclaw.plugin.json exists", (PLUGIN_DIR / "openclaw.plugin.json").is_file())
check("index.ts exists", (PLUGIN_DIR / "index.ts").is_file())
check("README.md exists", (PLUGIN_DIR / "README.md").is_file())
check("SECURITY.md exists", (PLUGIN_DIR / "SECURITY.md").is_file())

# ── Compiled dist output ───────────────────────────────────────────────────────
section("Compiled dist output (install-time artifacts)")
dist_js = PLUGIN_DIR / "dist" / "index.js"
dist_dts = PLUGIN_DIR / "dist" / "index.d.ts"
check("dist/index.js exists", dist_js.is_file(),
      "run: cd integrations/openclaw-aivan-plugin && npm run build")
check("dist/index.d.ts exists", dist_dts.is_file(),
      "run: cd integrations/openclaw-aivan-plugin && npm run build")
if dist_js.is_file():
    dist_js_text = dist_js.read_text()
    check("dist/index.js contains export function register",
          "export function register" in dist_js_text,
          "register() entry point missing from compiled output")
    check("dist/index.js is not empty", len(dist_js_text.strip()) > 0)

# ── package.json metadata ──────────────────────────────────────────────────────
section("package.json metadata")
pkg_path = PLUGIN_DIR / "package.json"
pkg: dict = {}
if pkg_path.is_file():
    pkg = json.loads(pkg_path.read_text())

check("name is @giraffetechnology/openclaw-aivan",
      pkg.get("name") == "@giraffetechnology/openclaw-aivan")
check("version present", bool(pkg.get("version")))
check('type is "module"', pkg.get("type") == "module")
check("description present", bool(pkg.get("description")))
check("repository.url present", bool((pkg.get("repository") or {}).get("url")))
check("license present", bool(pkg.get("license")))

# main/types must point to dist JS/DTS files
main_val = pkg.get("main", "")
types_val = pkg.get("types", "")
check('main points to dist/index.js (not bare index.js)',
      "dist" in main_val and main_val.endswith(".js"),
      f"got: {main_val!r}")
check('types points to dist/index.d.ts (not bare index.d.ts)',
      "dist" in types_val and types_val.endswith(".d.ts"),
      f"got: {types_val!r}")

# Resolve main/types relative to plugin dir and verify file exists
if main_val:
    main_path = (PLUGIN_DIR / main_val.lstrip("./")).resolve()
    check("main target file exists on disk", main_path.is_file(),
          f"resolved to {main_path}")
if types_val:
    types_path = (PLUGIN_DIR / types_val.lstrip("./")).resolve()
    check("types target file exists on disk", types_path.is_file(),
          f"resolved to {types_path}")

# exports field
exports = pkg.get("exports", {})
check("exports field present", bool(exports))
dot_export = exports.get(".", {})
check('exports["."] has "import" key', "import" in dot_export,
      f"got: {list(dot_export.keys())}")
check('exports["."]["import"] points to dist/index.js',
      "dist" in dot_export.get("import", "") and dot_export.get("import", "").endswith(".js"),
      f"got: {dot_export.get('import')!r}")

# ── OpenClaw compatibility metadata ───────────────────────────────────────────
section("OpenClaw 2026.6.9 compatibility metadata")
oc = pkg.get("openclaw", {})
check("openclaw.compat.pluginApi present",
      bool(oc.get("compat", {}).get("pluginApi")))
check("openclaw.build.openclawVersion present",
      bool(oc.get("build", {}).get("openclawVersion")))
check("openclawVersion targets >=2026.3.22 or later",
      "2026" in oc.get("build", {}).get("openclawVersion", ""),
      f"got: {oc.get('build', {}).get('openclawVersion')!r}")

# extensions must be a list of path strings (not object-array format)
exts = oc.get("extensions", [])
check("openclaw.extensions is a list", isinstance(exts, list),
      f"got type {type(exts).__name__}")
if isinstance(exts, list) and exts:
    check("openclaw.extensions uses path strings (not object-array)",
          all(isinstance(e, str) for e in exts),
          f"first entry type: {type(exts[0]).__name__}")
    check("openclaw.extensions entry points to a JS file",
          any(e.endswith(".js") for e in exts),
          f"entries: {exts}")
    for ext_path in exts:
        if isinstance(ext_path, str):
            resolved = (PLUGIN_DIR / ext_path.lstrip("./")).resolve()
            check(f"extensions entry {ext_path!r} exists on disk",
                  resolved.is_file(), f"resolved to {resolved}")

runtime_exts = oc.get("runtimeExtensions", [])
check("openclaw.runtimeExtensions present", bool(runtime_exts))
if runtime_exts:
    check("runtimeExtensions entry points to dist/index.js",
          any("dist" in e and e.endswith(".js") for e in runtime_exts),
          f"entries: {runtime_exts}")

# ── openclaw.plugin.json ───────────────────────────────────────────────────────
section("openclaw.plugin.json")
manifest_path = PLUGIN_DIR / "openclaw.plugin.json"
manifest: dict = {}
if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text())

check("id field present", bool(manifest.get("id")))
check('id is "openclaw-aivan"', manifest.get("id") == "openclaw-aivan")
check("name field present", bool(manifest.get("name")))
check("description field present", bool(manifest.get("description")))
check("version field present", bool(manifest.get("version")))
check("configSchema field present", "configSchema" in manifest)
activation = manifest.get("activation", {})
check("activation.onStartup is true", activation.get("onStartup") is True,
      "Gateway startup activation required")

# ── .gitignore must exclude node_modules but not dist ─────────────────────────
section("gitignore — node_modules excluded, dist NOT excluded")
gitignore_path = PLUGIN_DIR / ".gitignore"
if gitignore_path.is_file():
    gi_lines = [l.strip() for l in gitignore_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    check("node_modules/ in .gitignore", "node_modules/" in gi_lines or "node_modules" in gi_lines)
    check("dist/ NOT in .gitignore (dist must be committed)",
          "dist/" not in gi_lines and "dist" not in gi_lines,
          f"gitignore lines: {gi_lines}")
else:
    check(".gitignore exists in plugin dir", False)

# ── Environment variables and security ────────────────────────────────────────
section("Source security checks")
index_text = (PLUGIN_DIR / "index.ts").read_text() if (PLUGIN_DIR / "index.ts").is_file() else ""
check("No hardcoded API key in index.ts",
      "sk-" not in index_text and "Authorization" not in index_text)
check("AIVAN_API_KEY sent as X-AIVAN-API-Key header", "X-AIVAN-API-Key" in index_text)
check("AIVAN_API_KEY only read from env",
      "process.env?.AIVAN_API_KEY" in index_text or "process.env.AIVAN_API_KEY" in index_text)
check("export function register present in index.ts",
      "export function register" in index_text)

section("Environment variables documented")
readme_text = (PLUGIN_DIR / "README.md").read_text() if (PLUGIN_DIR / "README.md").is_file() else ""
check("AIVAN_BASE_URL documented in README", "AIVAN_BASE_URL" in readme_text)
check("AIVAN_API_KEY documented in README", "AIVAN_API_KEY" in readme_text)

section("Security policy")
sec_text = (PLUGIN_DIR / "SECURITY.md").read_text() if (PLUGIN_DIR / "SECURITY.md").is_file() else ""
check("No credential storage clause present", "credential" in sec_text.lower())
check("Human approval clause present", "human approval" in sec_text.lower())
check("No bypassing anti-bot clause present", "anti-bot" in sec_text.lower())
check("Local data boundary clause present", "sqlite" in sec_text.lower())
check("Risk screening disclaimer present", "decision support" in sec_text.lower())
check("Legal/compliance disclaimer present", "legal" in sec_text.lower())

section("Skill listing")
skill_path = ROOT / "skills" / "aivan-trade-salesperson" / "SKILL.md"
check("skills/aivan-trade-salesperson/SKILL.md exists", skill_path.is_file())
if skill_path.is_file():
    skill_text = skill_path.read_text()
    check("Skill slug defined", "aivan-trade-salesperson" in skill_text)
    check("Human approval requirement documented in skill", "human approval" in skill_text.lower())
    check("AIVAN_BASE_URL documented in skill", "AIVAN_BASE_URL" in skill_text)

print()
if failures:
    print(f"\033[31m{len(failures)} check(s) failed.\033[0m")
    sys.exit(1)
else:
    print(f"\033[32mAll checks passed.\033[0m")
