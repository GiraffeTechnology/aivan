"""Local lifecycle regressions for legacy recovery; no production services or SQL writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import textwrap

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "installer/runtime.py"
spec = importlib.util.spec_from_file_location("legacy_recovery_runtime", SOURCE)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

# A previous-controller dispatch fixture. The candidate startup below is real up
# to its subprocess boundary, including configuration and SQL-target validation.
LEGACY_CONTROLLER = textwrap.dedent('''\
    import json

    def start(root):
        config = json.loads((root / "config.json").read_text())
        assert "database_mode" not in config
        assert config["host_profile"] == "isolated"
        assert config["tenants"] and config["secrets"]
        (root / "run/legacy-restarted.json").write_text(json.dumps(config))
        return {"ok": True}
''')


def payload(path, name, controller=None, modern=False):
    path.mkdir(parents=True)
    files = {"runtime.py": controller or "# Candidate fixture\n"}
    if modern:
        files.update({"database_config.py": "# SQL-capable release\n",
                      "deployment_config.py": "# Deployment-capable release\n"})
    for filename, content in files.items():
        (path / filename).write_text(content)
    runtime.write_json(path / "manifest.json", {
        "release": name,
        "components": {"aivan": {"revision": "a" * 40}, "abcdyi": {}},
        "files": {name: hashlib.sha256(content.encode()).hexdigest()
                  for name, content in files.items()},
    })
    return path


def legacy_config():
    # Match the six-service controller's persisted pre-SQL-mode schema, rather
    # than using new_config() with modern fields accidentally left in place.
    ports = {name: 17000 + index for index, name in enumerate(runtime.SERVICES)}
    return {
        "version": 2,
        "private_data_provider_id": "local-provider-original",
        "bundled_private_data_provider_id": "local-provider-original",
        "host_profile": "isolated", "origin": "https://myaivan.example",
        "ports": ports,
        "tenants": {"tenant-a": "a" * 43, "tenant-b": "b" * 43},
        "secrets": {name: name + "-" + "s" * 64
                    for name in ("session", "database", "gltg", "abcdyi")},
        "fulfillment": {"port": ports["abcdyi"],
                        "tenants": runtime.fulfillment_tenants(["tenant-a", "tenant-b"])},
        "external": {},
        "language": {"url": "", "provider": "ctranslate2", "model": "", "model_dir": ""},
        "model": {"url": "", "name": ""},
    }


def installed(tmp_path, config=None, previous=True):
    root = tmp_path / "installation with spaces"
    runtime.check_root(root, initialize=True)
    for directory in ("releases", "data", "logs", "run", "backups"):
        (root / directory).mkdir(mode=0o700)
    old = payload(root / "releases/legacy", "legacy", LEGACY_CONTROLLER)
    runtime.set_current(root, old)
    config = legacy_config() if config is None else config
    # Noncanonical formatting detects whether recovery rewrites original bytes.
    (root / "config.json").write_text(json.dumps(config, indent=3) + "\n\n")
    (root / "config.json").chmod(0o600)
    (root / "data/business.txt").write_text("original business history")
    if previous:
        runtime.write_json(root / "previous.json", {"release": "older", "snapshot": "older-backup"})
    candidate = payload(tmp_path / "candidate", "candidate", modern=True)
    return root, old, candidate


def fail_candidate_bootstrap(monkeypatch, root):
    calls = []

    def bootstrap(command, **kwargs):
        # This is reached only after the real start() configuration validation
        # and environment() SQL-target selection have succeeded.
        calls.append(kwargs["env"])
        (root / "data/business.txt").write_text("failed candidate mutation")
        raise RuntimeError("candidate bootstrap failed")

    monkeypatch.setattr(runtime.subprocess, "run", bootstrap)
    return calls


def test_raw_legacy_config_requires_previous_controller(tmp_path):
    root, old, _ = installed(tmp_path)
    config = runtime.read_json(root / "config.json")
    runtime.validate_config(config)
    with pytest.raises(ValueError, match="private database configuration"):
        runtime.environment(root, old, config)
    upgraded = runtime.upgrade_config(config)
    assert runtime.environment(root, old, upgraded)["AIVAN_DB_URL"].startswith("sqlite:///")
    assert "database_mode" not in config


@pytest.mark.parametrize("has_previous", [True, False])
@pytest.mark.parametrize("version", [1, 2])
def test_failed_legacy_upgrade_restarts_original_controller_and_preserves_state(
        tmp_path, monkeypatch, has_previous, version):
    config = legacy_config()
    if version == 1:
        config["version"] = 1
        config["ports"].pop("abcdyi")
        config["secrets"].pop("abcdyi")
        for key in ("fulfillment", "private_data_provider_id", "bundled_private_data_provider_id"):
            config.pop(key)
    root, old, candidate = installed(tmp_path, config, previous=has_previous)
    original = (root / "config.json").read_bytes()
    previous = (root / "previous.json").read_bytes() if has_previous else None
    calls = fail_candidate_bootstrap(monkeypatch, root)
    with pytest.raises(RuntimeError, match="candidate bootstrap failed"):
        runtime.install(root, candidate, ["ignored-new-tenant"], 0, False)
    assert len(calls) == 1
    assert runtime.release(root) == old
    assert (root / "config.json").read_bytes() == original
    assert runtime.read_json(root / "run/legacy-restarted.json") == json.loads(original)
    assert (root / "data/business.txt").read_text() == "original business history"
    snapshots = list((root / "backups").iterdir())
    assert len(snapshots) == 1
    assert (snapshots[0] / "config.json").read_bytes() == original
    assert (snapshots[0] / "failed-upgrade-data/business.txt").read_text() == "failed candidate mutation"
    if previous is None:
        assert not (root / "previous.json").exists()
    else:
        assert (root / "previous.json").read_bytes() == previous
    assert runtime.read_json(root / "run/ports.json")["services"]["web"]["port"] == 17004


def sql_file(path):
    runtime.write_json(path, {"version": 1, "databases": {
        name: {"url": f"mysql+{driver}://fixture@db.example/{name}"}
        for name, driver in (("aivan", "pymysql"), ("abcdyi", "aiomysql"), ("database", "pymysql"))
    }})
    return path


def test_failed_attempt_to_select_external_sql_never_restarts_legacy_sqlite(tmp_path, monkeypatch):
    root, old, candidate = installed(tmp_path)
    original = (root / "config.json").read_bytes()
    database = sql_file(tmp_path / "private-sql.json")
    database_before = database.read_bytes()
    calls = fail_candidate_bootstrap(monkeypatch, root)
    with pytest.raises(RuntimeError, match="candidate bootstrap failed"):
        runtime.install(root, candidate, [], 0, False, database_config_file=database)
    assert len(calls) == 1
    assert calls[0]["AIVAN_DB_URL"].startswith("mysql+pymysql://")
    assert not (root / "run/legacy-restarted.json").exists()
    assert runtime.release(root) == old
    assert (root / "config.json").read_bytes() == original
    assert database.read_bytes() == database_before


def test_existing_external_sql_recovery_retains_exact_database_targets(tmp_path, monkeypatch):
    database = sql_file(tmp_path / "private-sql.json")
    config = legacy_config()
    config.update(database_mode="external", database_config_file=str(database))
    root, old, candidate = installed(tmp_path, config)
    original = (root / "config.json").read_bytes()
    database_before = database.read_bytes()
    seen = []

    def start(root):
        config = runtime.read_json(root / "config.json")
        runtime.validate_config(config)
        seen.append(runtime.environment(root, runtime.release(root), config))
        if len(seen) == 1:
            raise RuntimeError("external candidate startup failed")
        return {"ok": True}

    monkeypatch.setattr(runtime, "start", start)
    with pytest.raises(RuntimeError, match="external candidate startup failed"):
        runtime.install(root, candidate, [], 0, False)
    assert len(seen) == 2
    for key in ("AIVAN_DB_URL", "DATABASE_URL", "GIRAFFE_DB_DATABASE_URL"):
        assert seen[0][key] == seen[1][key]
        assert seen[1][key].startswith("mysql+")
    assert runtime.release(root) == old
    assert (root / "config.json").read_bytes() == original
    assert database.read_bytes() == database_before
    assert not (root / "run/legacy-restarted.json").exists()


def test_changed_external_sql_target_does_not_restart_previous_store(tmp_path, monkeypatch):
    original_database = sql_file(tmp_path / "original-sql.json")
    requested_database = sql_file(tmp_path / "requested-sql.json")
    config = legacy_config()
    config.update(database_mode="external", database_config_file=str(original_database))
    root, old, candidate = installed(tmp_path, config)
    calls = fail_candidate_bootstrap(monkeypatch, root)
    with pytest.raises(RuntimeError, match="candidate bootstrap failed"):
        runtime.install(root, candidate, [], 0, False, database_config_file=requested_database)
    assert len(calls) == 1
    assert runtime.release(root) == old
    assert runtime.read_json(root / "config.json") == config
    assert not (root / "run/legacy-restarted.json").exists()


def test_legacy_external_sql_is_not_reclassified_as_bundled_recovery(tmp_path, monkeypatch):
    config = legacy_config()
    config["external"]["aivan_database_url"] = "mysql+pymysql://fixture@db.example/existing"
    root, old, candidate = installed(tmp_path, config)
    original = (root / "config.json").read_bytes()
    calls = fail_candidate_bootstrap(monkeypatch, root)
    # Preserve the existing fail-closed SQL path. The isolated compatibility
    # branch must not accept a legacy configuration selecting external SQL.
    with pytest.raises(ValueError, match="private database configuration"):
        runtime.install(root, candidate, [], 0, False)
    assert len(calls) == 1
    assert calls[0]["AIVAN_DB_URL"] == config["external"]["aivan_database_url"]
    assert runtime.release(root) == old
    assert (root / "config.json").read_bytes() == original
    assert not (root / "run/legacy-restarted.json").exists()


def test_legacy_recovery_rejects_modified_previous_controller(tmp_path, monkeypatch):
    root, old, candidate = installed(tmp_path)
    (old / "runtime.py").write_text("raise AssertionError('must not execute modified controller')\n")
    fail_candidate_bootstrap(monkeypatch, root)
    with pytest.raises(ValueError, match="integrity mismatch"):
        runtime.install(root, candidate, [], 0, False)
    assert not (root / "run/legacy-restarted.json").exists()


def test_explicit_rollback_keeps_external_sql_compatibility_guard(tmp_path):
    database = sql_file(tmp_path / "private-sql.json")
    config = legacy_config()
    config.update(database_mode="external", database_config_file=str(database))
    root, old, _ = installed(tmp_path, config)
    with pytest.raises(RuntimeError, match="cannot preserve the configured external databases"):
        runtime.config_for_release(config, old)
    assert runtime.read_json(root / "config.json") == config


@pytest.mark.parametrize("command", ["restart", "recover", "serve"])
@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
def test_cli_restart_preflight_preserves_services_when_external_credentials_are_missing(
        tmp_path, monkeypatch, command, service):
    config = legacy_config()
    config["database_mode"] = "isolated"
    config["external"][service] = f"https://{service}.example.invalid"
    root, _, _ = installed(tmp_path, config)
    original_config = (root / "config.json").read_bytes()
    original_pointer = (root / "previous.json").read_bytes()
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped before credential validation"))
    monkeypatch.setattr(runtime, "start", lambda _root: pytest.fail("Started before credential validation"))
    monkeypatch.setattr(runtime, "supervise", lambda _root: pytest.fail("Supervised before credential validation"))
    with pytest.raises(ValueError, match="credentials"):
        runtime.main(["--prefix", str(root), command])
    assert (root / "config.json").read_bytes() == original_config
    assert (root / "previous.json").read_bytes() == original_pointer
