"""Cross-version rollback regressions without starting services or contacting SQL."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import textwrap

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "installer"

# Keep the current controller's real start() and main(). Only the process/health
# boundaries are inert, including when rollback imports a fresh controller.
PROCESS_BOUNDARIES = textwrap.dedent('''\
    def status(root):
        return {"running": True, "processes": {}}

    def stop(root):
        with open(root / "run/events", "a") as stream:
            stream.write("stop\\n")
        return {"stopped": True}

    def wait_healthy(root, seconds=45):
        write_json(root / "run/current-started.json", {
            "controller": __file__, "config": read_json(root / "config.json")})
        return {"ok": True}
''')

OLD_CONTROLLER = textwrap.dedent('''\
    import fcntl
    import importlib.util
    import json
    from pathlib import Path

    def start(root):
        # Dispatch must retain the parent lock without entering another CLI.
        with open(root / ".operation.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("Rollback released its operation lock")
        helper_path = Path(__file__).with_name("deployment_config.py")
        spec = importlib.util.spec_from_file_location("old_helpers", helper_path)
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)
        config = json.loads((root / "config.json").read_text())
        assert helpers.credentials(config) == {"old_signature": True}
        (root / "run/old-started.json").write_text(json.dumps({
            "controller": __file__, "config": config}))
        if (root / "run/fail-target").exists():
            config["origin"] = "https://failed-start.example"
            (root / "config.json").write_text(json.dumps(config))
            if (root / "run/tamper-current").exists():
                with open(root / "releases/new/runtime.py", "a") as stream:
                    stream.write("\\n# Changed after target startup\\n")
            raise RuntimeError("old target startup failed")
        return {"ok": True}

    def main(*args):
        raise AssertionError("Must not invoke the target CLI under the operation lock")
''')

# The older helper deliberately lacks the newer keyword and permits absent
# external credentials, reproducing the version boundary that broke r17.
OLD_HELPERS = textwrap.dedent('''\
    def validate(config, *, endpoint):
        pass

    def credentials(config):
        return {"old_signature": True}
''')


def load_controller(path):
    spec = importlib.util.spec_from_file_location("cross_version_runtime", path)
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    return controller


def write_payload(path, files):
    path.mkdir(parents=True)
    for filename, content in files.items():
        (path / filename).write_text(content)
    (path / "manifest.json").write_text(json.dumps({
        "release": path.name,
        "components": {"aivan": {"revision": "a" * 40}, "abcdyi": {}},
        "files": {name: hashlib.sha256(content.encode()).hexdigest()
                  for name, content in files.items()},
    }))


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    controller = load_controller(INSTALLER / "runtime.py")
    root = tmp_path / "installation with spaces"
    controller.check_root(root, initialize=True)
    for directory in ("releases", "run", "data", "logs", "backups"):
        (root / directory).mkdir(mode=0o700)
    common = {name: (INSTALLER / name).read_text()
              for name in ("deployment_config.py", "database_config.py")}
    write_payload(root / "releases/new", {
        **common, "runtime.py": (INSTALLER / "runtime.py").read_text() + PROCESS_BOUNDARIES})
    write_payload(root / "releases/old", {
        **common, "runtime.py": OLD_CONTROLLER, "deployment_config.py": OLD_HELPERS})
    controller.set_current(root, root / "releases/new")
    config = controller.new_config(["tenant-a"])
    config["database_mode"] = "isolated"
    controller.write_json(root / "config.json", config)
    controller.write_json(root / "previous.json", {"release": "old", "snapshot": "keep"})
    (root / "data/business.txt").write_text("existing business history")
    # Match the real installed launcher: __file__ initially passes through current.
    return load_controller(root / "current/runtime.py"), root, config


@pytest.mark.parametrize("database_mode", ["isolated", "external"])
def test_rollback_dispatches_matching_controller_and_old_helper(installed, database_mode):
    runtime, root, config = installed
    if database_mode == "external":
        sql = root / "private-sql.json"
        runtime.write_json(sql, {"version": 1, "databases": {
            name: {"url": f"mysql+{driver}://fixture@db.example/{name}"}
            for name, driver in (("aivan", "pymysql"), ("abcdyi", "aiomysql"),
                                 ("database", "pymysql"))}})
        config.update(database_mode="external", database_config_file=str(sql))
        runtime.write_json(root / "config.json", config)
    original = (root / "config.json").read_bytes()
    previous = (root / "previous.json").read_bytes()

    assert runtime.main(["--prefix", str(root), "rollback"]) == 0

    assert runtime.release(root) == root / "releases/old"
    started = runtime.read_json(root / "run/old-started.json")
    assert started == {"controller": str(root / "releases/old/runtime.py"), "config": config}
    assert not (root / "run/current-started.json").exists()
    assert (root / "config.json").read_bytes() == original
    assert (root / "previous.json").read_bytes() == previous
    assert (root / "data/business.txt").read_text() == "existing business history"


def test_failed_target_restores_matching_verified_current_controller(installed):
    runtime, root, config = installed
    (root / "run/fail-target").touch()
    previous = (root / "previous.json").read_bytes()

    with pytest.raises(RuntimeError, match="old target startup failed"):
        runtime.main(["--prefix", str(root), "rollback"])

    assert runtime.release(root) == root / "releases/new"
    assert (root / "run/old-started.json").exists()
    restored = runtime.read_json(root / "run/current-started.json")
    assert restored == {"controller": str(root / "releases/new/runtime.py"), "config": config}
    assert runtime.read_json(root / "config.json") == config
    assert (root / "previous.json").read_bytes() == previous
    assert (root / "data/business.txt").read_text() == "existing business history"


@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
@pytest.mark.parametrize("credentials", ["missing", "invalid"])
def test_rollback_strict_preflight_precedes_stop_or_pointer_change(
        installed, monkeypatch, service, credentials):
    runtime, root, config = installed
    config["external"][service] = f"https://{service}.example.invalid"
    if credentials == "invalid":
        path = root / "private-credentials.json"
        runtime.write_json(path, {"version": 1, "services": {service: {}}})
        config["service_credentials_file"] = str(path)
    runtime.write_json(root / "config.json", config)
    original = (root / "config.json").read_bytes()
    previous = (root / "previous.json").read_bytes()
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped before validation"))
    monkeypatch.setattr(runtime, "set_current", lambda *_args: pytest.fail("Switched before validation"))

    with pytest.raises(ValueError, match="credential"):
        runtime.main(["--prefix", str(root), "rollback"])

    assert runtime.release(root) == root / "releases/new"
    assert (root / "config.json").read_bytes() == original
    assert (root / "previous.json").read_bytes() == previous
    assert not (root / "run/old-started.json").exists()


def test_rollback_verifies_target_before_stopping(installed, monkeypatch):
    runtime, root, _ = installed
    (root / "releases/old/runtime.py").write_text("raise AssertionError('unverified')\n")
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped before verification"))
    with pytest.raises(ValueError, match="integrity mismatch"):
        runtime.main(["--prefix", str(root), "rollback"])
    assert runtime.release(root) == root / "releases/new"


def test_failed_target_verifies_restored_controller_before_execution(installed):
    runtime, root, config = installed
    (root / "run/fail-target").touch()
    (root / "run/tamper-current").touch()
    with pytest.raises(ValueError, match="integrity mismatch"):
        runtime.main(["--prefix", str(root), "rollback"])
    assert runtime.release(root) == root / "releases/new"
    assert runtime.read_json(root / "config.json") == config
    assert not (root / "run/current-started.json").exists()
