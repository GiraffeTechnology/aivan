"""Installed runtime candidate identity; no service startup."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "installer"
sys.path.insert(0, str(INSTALLER))
spec = importlib.util.spec_from_file_location("installed_candidate_test_runtime", INSTALLER / "runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

BASE = "a" * 40
CURRENT = "b" * 40


def manifest():
    identity = {"revision": CURRENT, "upstream_tree": "c" * 40}
    return {"deployment_candidate": identity,
            "components": {"aivan": {"revision": BASE, "selected_source_candidate": dict(identity)}}}


@pytest.fixture
def environment_call(tmp_path, monkeypatch):
    targets = {name: {"url": "mysql+pymysql://example.invalid/synthetic_" + name, "schema": "synthetic_" + name}
               for name in ("aivan", "database", "abcdyi")}
    monkeypatch.setattr(runtime, "load_database_module", lambda: SimpleNamespace(configured_targets=lambda *_: targets))
    monkeypatch.delenv("AIVAN_RESERVED_PORTS", raising=False)
    tenants = {"tenant-a": "synthetic-test-key-not-a-real-credential-000000"}
    ports = {name: 19000 + index for index, name in enumerate(runtime.SERVICES)}
    config = {"tenants": tenants, "ports": ports, "database_mode": "external", "external": {},
              "origin": "https://example.invalid", "reserved_ports": [], "runtime_threads": 2,
              "secrets": {name: "synthetic-local-" + name + "-0000000000000000000000000000"
                          for name in ("session", "database", "gltg", "abcdyi")},
              "fulfillment": {"tenants": runtime.fulfillment_tenants(tenants)},
              "private_data_provider_id": "synthetic-provider", "service_credentials_file": "",
              "language": {"url": "", "provider": "ctranslate2", "model": "", "model_dir": ""},
              "model": {"url": "", "name": ""}, "channels": {"email_enabled": False}}
    release = tmp_path / "release"
    release.mkdir()

    def invoke(value):
        path = release / "manifest.json"
        path.write_text(json.dumps(value))
        original = path.read_bytes()
        result = runtime.environment(tmp_path / "unused-prefix", release, config)
        assert path.read_bytes() == original
        return result

    return invoke


@pytest.mark.parametrize("shape,expected", [("both", CURRENT), ("deployment", CURRENT),
                                           ("selected", CURRENT), ("legacy", BASE)])
def test_runtime_reports_executed_candidate_without_rewriting_legacy_provenance(environment_call, shape, expected):
    value = manifest()
    if shape in {"selected", "legacy"}:
        value.pop("deployment_candidate")
    if shape in {"deployment", "legacy"}:
        value["components"]["aivan"].pop("selected_source_candidate")
    before = copy.deepcopy(value)
    assert environment_call(value)["AIVAN_CANDIDATE_SHA"] == expected
    assert value == before and value["components"]["aivan"]["revision"] == BASE


@pytest.mark.parametrize("field", ["deployment_candidate", "selected_source_candidate"])
@pytest.mark.parametrize("invalid", [None, "not-an-object", {}, {"revision": "short"}, {"revision": 7}])
def test_invalid_explicit_candidate_cannot_fall_back_to_base_identity(environment_call, field, invalid):
    value = manifest()
    if field == "deployment_candidate":
        value[field] = invalid
    else:
        value["components"]["aivan"][field] = invalid
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


def test_conflicting_current_candidate_claims_fail_instead_of_reporting_either(environment_call):
    value = manifest()
    value["components"]["aivan"]["selected_source_candidate"]["revision"] = "d" * 40
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


@pytest.mark.parametrize("revision", [None, "short", 7])
def test_invalid_legacy_revision_is_not_reported_as_an_exact_candidate(environment_call, revision):
    value = {"components": {"aivan": {"revision": revision}}}
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


@pytest.mark.parametrize("shape", ["both", "deployment", "selected"])
def test_explicit_null_claims_never_degrade_to_legacy(environment_call, shape):
    value = {"components": {"aivan": {"revision": BASE}}}
    if shape in {"both", "deployment"}:
        value["deployment_candidate"] = None
    if shape in {"both", "selected"}:
        value["components"]["aivan"]["selected_source_candidate"] = None
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


def test_candidate_tree_claims_must_not_conflict(environment_call):
    value = manifest()
    value["components"]["aivan"]["selected_source_candidate"]["upstream_tree"] = "d" * 40
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


@pytest.mark.parametrize("shape", [None, [], {}, {"components": None},
                                   {"components": {"aivan": None}}])
def test_malformed_manifest_fails_with_candidate_error(environment_call, shape):
    with pytest.raises(ValueError, match="candidate"):
        environment_call(shape)


@pytest.mark.parametrize("field", ["deployment_candidate", "selected_source_candidate"])
@pytest.mark.parametrize("tree", [None, "short", 7, "G" * 40])
def test_invalid_supplied_candidate_tree_is_rejected(environment_call, field, tree):
    value = manifest()
    claim = value[field] if field == "deployment_candidate" else value["components"]["aivan"][field]
    claim["upstream_tree"] = tree
    with pytest.raises(ValueError, match="candidate"):
        environment_call(value)


def test_revision_only_candidate_manifest_remains_supported(environment_call):
    value = manifest()
    value["deployment_candidate"].pop("upstream_tree")
    value["components"]["aivan"]["selected_source_candidate"].pop("upstream_tree")
    assert environment_call(value)["AIVAN_CANDIDATE_SHA"] == CURRENT
