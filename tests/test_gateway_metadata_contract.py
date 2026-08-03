"""Gateway-facing metadata contract tests.

Static validation of everything OpenClaw Gateway relies on to discover and
install AIVAN: the plugin manifest, the npm package entry points, the built
dist/ entry the Gateway actually loads, and the ClawHub skill listing. These
tests are the offline counterpart of the scripts/run_aivan_openclaw_* checks
and must stay in sync with the current registerAgentHarness plugin contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "integrations" / "openclaw-aivan-plugin"
SKILL_DIR = ROOT / "skills" / "aivan-trade-salesperson"
EXPECTED_TOOLS = [
    "aivan.health",
    "aivan.forwardEvent",
    "aivan.openDashboard",
    "aivan.getPendingDrafts",
    "aivan.approveDraft",
    "aivan.rejectDraft",
]

KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _manifest() -> dict:
    return json.loads((PLUGIN_DIR / "openclaw.plugin.json").read_text(encoding="utf-8"))


def _pkg() -> dict:
    return json.loads((PLUGIN_DIR / "package.json").read_text(encoding="utf-8"))


# ── Gateway discovery: manifest ───────────────────────────────────────────────

def test_plugin_manifest_exists_and_is_valid_json():
    manifest = _manifest()
    assert isinstance(manifest, dict)


def test_plugin_manifest_required_fields():
    manifest = _manifest()
    for key in ("id", "name", "description", "version", "configSchema"):
        assert manifest.get(key), f"openclaw.plugin.json missing {key!r}"


def test_plugin_id_is_stable_and_kebab_case():
    manifest = _manifest()
    assert manifest["id"] == "openclaw-aivan"
    assert KEBAB_CASE.match(manifest["id"])


def test_plugin_activates_on_startup():
    assert _manifest().get("activation", {}).get("onStartup") is True


def test_plugin_config_schema_has_aivan_base_url():
    props = _manifest().get("configSchema", {}).get("properties", {})
    assert "aivanBaseUrl" in props
    assert {"connectTimeoutMs", "readTimeoutMs", "maxRetries"} <= set(props)


def test_manifest_declares_exact_registered_tool_contract():
    manifest = _manifest()
    assert manifest["contracts"]["tools"] == EXPECTED_TOOLS
    metadata = manifest["contracts"]["toolMetadata"]
    assert metadata["aivan.approveDraft"]["optional"] is True
    assert metadata["aivan.rejectDraft"]["optional"] is True
    source = (PLUGIN_DIR / "index.ts").read_text(encoding="utf-8")
    for tool in EXPECTED_TOOLS:
        assert f'"{tool}"' in source


# ── Gateway install: package entry points ────────────────────────────────────

def test_package_name_is_scoped_npm_name():
    assert _pkg()["name"] == "@giraffetechnology/openclaw-aivan"


def test_package_entry_points_resolve_to_committed_dist():
    pkg = _pkg()
    assert pkg["main"] == "./dist/index.js"
    assert pkg["types"] == "./dist/index.d.ts"
    dot = pkg.get("exports", {}).get(".", {})
    assert dot.get("import") == "./dist/index.js"
    assert dot.get("types") == "./dist/index.d.ts"
    assert (PLUGIN_DIR / "dist" / "index.js").is_file(), "committed dist/index.js missing"
    assert (PLUGIN_DIR / "dist" / "index.d.ts").is_file(), "committed dist/index.d.ts missing"
    assert (PLUGIN_DIR / "dist" / "intent-boundary.json").is_file(), "runtime intent boundary missing"


def test_openclaw_extensions_point_to_dist_entry():
    openclaw_meta = _pkg().get("openclaw", {})
    for key in ("extensions", "runtimeExtensions"):
        entries = openclaw_meta.get(key)
        assert entries == ["./dist/index.js"], f"openclaw.{key} must point at dist entry"


def test_stage3_versions_and_compatibility_are_aligned():
    package = _pkg()
    manifest = _manifest()
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    release = json.loads((PLUGIN_DIR / "release-manifest.json").read_text(encoding="utf-8"))
    assert package["version"] == manifest["version"] == release["release"] == "0.3.0"
    assert "version: 0.3.0" in skill
    assert package["engines"]["node"] == ">=22.19.0"
    assert package["openclaw"]["build"]["openclawVersion"] == "2026.7.2"
    assert package["openclaw"]["build"]["pluginSdkVersion"] == "2026.6.8"
    assert release["openclawBaseline"]["commit"] == "1e06fd443033b8aa2fd638ee66b7fdad1168b8aa"


def test_skill_and_harness_share_intent_boundary_and_pass_through():
    boundary = json.loads((PLUGIN_DIR / "intent-boundary.json").read_text(encoding="utf-8"))
    source = (PLUGIN_DIR / "index.ts").read_text(encoding="utf-8")
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert boundary["intent"] == "trade-sourcing"
    assert 'from "./intent-boundary.json"' in source
    assert "isTradeSourcingIntent(params)" in source
    assert "outside trade-sourcing boundary" in source
    assert "intent-boundary.json" in skill
    assert "explicit pass-through" in skill


# ── Entrypoint contract: registerAgentHarness via default plugin entry ───────

def test_dist_entry_registers_agent_harness():
    dist = (PLUGIN_DIR / "dist" / "index.js").read_text(encoding="utf-8")
    assert "registerAgentHarness" in dist
    assert "export default" in dist or "exports.default" in dist


def test_source_and_dist_agree_on_harness_id():
    src = (PLUGIN_DIR / "index.ts").read_text(encoding="utf-8")
    dist = (PLUGIN_DIR / "dist" / "index.js").read_text(encoding="utf-8")
    for text, name in ((src, "index.ts"), (dist, "dist/index.js")):
        assert '"openclaw-aivan"' in text, f"{name} lost the openclaw-aivan harness id"


# ── Skill listing: ClawHub discovery ──────────────────────────────────────────

def test_skill_listing_exists():
    assert (SKILL_DIR / "SKILL.md").is_file()


def test_skill_slug_matches_directory_and_format():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^slug:\s*(\S+)", text, re.MULTILINE)
    assert match, "SKILL.md missing slug"
    slug = match.group(1)
    assert slug == SKILL_DIR.name == "aivan-trade-salesperson"
    assert KEBAB_CASE.match(slug)


def test_skill_references_plugin_package():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "@giraffetechnology/openclaw-aivan" in text
