#!/usr/bin/env python3
"""Validate ClawHub plugin package metadata and structure for AIVAN."""
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


section("Plugin directory structure")
check("integrations/openclaw-aivan-plugin/ exists", PLUGIN_DIR.is_dir())
check("package.json exists", (PLUGIN_DIR / "package.json").is_file())
check("index.ts exists", (PLUGIN_DIR / "index.ts").is_file())
check("README.md exists", (PLUGIN_DIR / "README.md").is_file())
check("SECURITY.md exists", (PLUGIN_DIR / "SECURITY.md").is_file())

section("package.json metadata")
pkg_path = PLUGIN_DIR / "package.json"
pkg: dict = {}
if pkg_path.is_file():
    pkg = json.loads(pkg_path.read_text())

check("name is @giraffetechnology/openclaw-aivan", pkg.get("name") == "@giraffetechnology/openclaw-aivan")
check("version present", bool(pkg.get("version")))
check('type is "module"', pkg.get("type") == "module")
check("description present", bool(pkg.get("description")))
check("repository.url present", bool((pkg.get("repository") or {}).get("url")))
check("license present", bool(pkg.get("license")))

section("OpenClaw compatibility metadata")
oc = pkg.get("openclaw", {})
check("openclaw.compat.pluginApi present", bool(oc.get("compat", {}).get("pluginApi")))
check("openclaw.build.openclawVersion present", bool(oc.get("build", {}).get("openclawVersion")))
exts = oc.get("extensions", [])
ext_ids = {e.get("id") for e in exts}
check("aivan.health extension defined", "aivan.health" in ext_ids)
check("aivan.forwardEvent extension defined", "aivan.forwardEvent" in ext_ids)
check("aivan.openDashboard extension defined", "aivan.openDashboard" in ext_ids)
check("aivan.getPendingDrafts extension defined", "aivan.getPendingDrafts" in ext_ids)
check("aivan.approveDraft extension defined", "aivan.approveDraft" in ext_ids)
check("aivan.rejectDraft extension defined", "aivan.rejectDraft" in ext_ids)

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

section("No secrets in tracked files")
index_text = (PLUGIN_DIR / "index.ts").read_text() if (PLUGIN_DIR / "index.ts").is_file() else ""
check("No hardcoded API key in index.ts", "sk-" not in index_text and "Bearer " not in index_text.replace("Bearer ${", ""))
check("AIVAN_API_KEY only read from env", 'process.env?.AIVAN_API_KEY' in index_text or 'process.env.AIVAN_API_KEY' in index_text)

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
