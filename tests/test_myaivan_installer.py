"""Independent adversarial lifecycle tests; no production processes or data."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'installer/runtime.py'
spec = importlib.util.spec_from_file_location('reviewed_runtime', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class InstallerReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = self.work / 'MyAivan Server'
        self.root.mkdir(mode=0o700)
    def payload(self, name, content='safe'):
        target = self.work / name
        target.mkdir()
        (target / 'safe.txt').write_text(content)
        manifest={'release':name,'components':{'aivan':{'revision':'a'*40}},'files':{'safe.txt':hashlib.sha256(content.encode()).hexdigest()}}
        (target / 'manifest.json').write_text(json.dumps(manifest))
        return target
    def installed(self):
        m.check_root(self.root, initialize=True)
        m.install(self.root,self.payload('v1'),['tenant-a','tenant-b'],0,True, isolated_sqlite=True)
        return self.root
    def test_reject_extra_nested_manifest(self):
        p=self.payload('v1'); (p/'nested').mkdir(); (p/'nested/manifest.json').write_text('extra')
        with self.assertRaises(ValueError): m.verify_payload(p)
    def test_reject_payload_symlink(self):
        p=self.payload('v1'); (p/'link').symlink_to('safe.txt')
        with self.assertRaises(ValueError): m.verify_payload(p)
    def test_reject_foreign_nonempty_prefix(self):
        (self.root/'keep.txt').write_text('foreign data')
        with self.assertRaises(ValueError): m.check_root(self.root, initialize=True)
        self.assertEqual((self.root/'keep.txt').read_text(),'foreign data')
    def test_reject_managed_child_symlink(self):
        m.check_root(self.root, initialize=True)
        outside=self.work/'outside';outside.mkdir(); (self.root/'data').symlink_to(outside)
        with self.assertRaises(ValueError):m.check_root(self.root)
    def test_invalid_process_records_never_owned(self):
        for record in [{'pid':-1,'identity':None},{'pid':0,'identity':None},{'pid':999999999,'identity':None}]:
            with self.subTest(record=record): self.assertFalse(m.owned_process(record))
    def test_reinstall_preserves_config_and_data(self):
        self.installed(); (self.root/'data/business.txt').write_text('existing business')
        prior=(self.root/'config.json').read_bytes()
        m.install(self.root,self.work/'v1',['different-tenant'],0,True)
        self.assertEqual(prior,(self.root/'config.json').read_bytes())
        self.assertEqual((self.root/'data/business.txt').read_text(),'existing business')
    def test_same_release_different_content_rejected_before_stop(self):
        self.installed(); p=self.work/'v1';(p/'safe.txt').write_text('changed')
        manifest=json.loads((p/'manifest.json').read_text());manifest['files']['safe.txt']=hashlib.sha256(b'changed').hexdigest();(p/'manifest.json').write_text(json.dumps(manifest))
        with mock.patch.object(m,'stop') as stop:
            with self.assertRaises(RuntimeError):m.install(self.root,p,['tenant-a'],0,True)
            stop.assert_not_called()
    def test_failed_upgrade_restores_data_and_preserves_failure_evidence(self):
        self.installed(); (self.root/'data/business.txt').write_text('before upgrade')
        calls=[]
        def start(root):
            calls.append(m.release(root).name)
            if len(calls)==1:
                (root/'data/business.txt').write_text('failed mutation')
                raise RuntimeError('test injected failed startup')
            return {'ok':True}
        with mock.patch.object(m,'start',side_effect=start):
            with self.assertRaisesRegex(RuntimeError,'test injected'):m.install(self.root,self.payload('v2'),['tenant-a'],0,False)
        self.assertEqual(calls,['v2','v1'])
        self.assertEqual(m.release(self.root).name,'v1')
        self.assertEqual((self.root/'data/business.txt').read_text(),'before upgrade')
        failed=list((self.root/'backups').glob('*/failed-upgrade-data/business.txt'))
        self.assertEqual(len(failed),1)
        self.assertEqual(failed[0].read_text(),'failed mutation')
    def test_uninstall_retains_data_config_and_release(self):
        self.installed();(self.root/'data/business.txt').write_text('keep')
        with contextlib.redirect_stdout(io.StringIO()):m.main(['--prefix',str(self.root),'uninstall'])
        self.assertFalse((self.root/'current').exists())
        self.assertFalse((self.root/'myaivan').exists())
        self.assertEqual((self.root/'data/business.txt').read_text(),'keep')
        self.assertTrue((self.root/'config.json').is_file())
        self.assertTrue((self.root/'releases/v1').is_dir())
    def test_failed_new_supervisor_preserves_foreign_state(self):
        self.installed();config=m.read_json(self.root/'config.json')
        foreign={'supervisor':{'pid':999999999,'identity':'123'},'children':{}}
        m.write_json(self.root/'run/processes.json',foreign)
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',config['ports']['language']));occupied.listen()
            with mock.patch.object(m, 'bind_available_port', side_effect=OSError('test listener failure')):
                with self.assertRaises(OSError):m.supervise(self.root)
        self.assertTrue((self.root/'run/processes.json').exists(),'failed supervisor deleted state it did not write')
        self.assertEqual(m.read_json(self.root/'run/processes.json'),foreign)




def test_installer_config_has_distinct_tenants_and_ports():
    config = m.new_config(["tenant-a", "tenant-b"])
    m.validate_config(config)
    assert len(set(config["tenants"].values())) == 2
    assert len(set(config["ports"].values())) == 6
    assert all(1024 <= port <= 65535 for port in config["ports"].values())


def test_installer_rejects_duplicate_tenant_credentials():
    config = m.new_config(["tenant-a", "tenant-b"])
    config["tenants"]["tenant-b"] = config["tenants"]["tenant-a"]
    import pytest
    with pytest.raises(ValueError, match="distinct"):
        m.validate_config(config)


def test_installer_reservations_are_environment_values(monkeypatch):
    monkeypatch.setenv("AIVAN_RESERVED_PORTS", "443,14443")
    config = m.new_config(["tenant-a"])
    config["host_profile"] = "ctyun"
    assert config["reserved_ports"] == [443, 14443]
    listener, selected = m.bind_available_port(14443, set(config["reserved_ports"]), set())
    try:
        assert selected not in config["reserved_ports"]
    finally:
        listener.close()


def test_installer_environment_does_not_inherit_host_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret-not-for-package")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "https://must-not-send.invalid")
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / "manifest.json").write_text(json.dumps({"components": {"aivan": {"revision": "a" * 40}}}))
    config = m.new_config(["tenant-a", "tenant-b"])
    config["database_mode"] = "isolated"
    env = m.environment(tmp_path, rel, config)
    assert "OPENAI_API_KEY" not in env
    assert env["OPENCLAW_BASE_URL"] == ""
    assert env["OPENCLAW_MOCK_MODE"] == "false"
    assert env["GPM_LLM_RUNTIME_MODE"] == "live"
    assert env["AIVAN_REQUIRE_HUMAN_APPROVAL"] == "true"
    assert env["GIRAFFE_DB_REQUIRE_LANGUAGE_SKILL"] == "true"
    assert env["AIVAN_PERSIST_GIRAFFE_DB_GRAPH"] == "true"
    assert env["GIRAFFE_TRANSLATION_PROVIDER"] == "ctranslate2"
    assert json.loads(env["GPM_TENANT_API_KEYS"]) == config["tenants"]
    assert "AIVAN_TENANT_ID" not in env


def test_installer_process_identity_rejects_current_unowned_command(tmp_path):
    import os
    assert not m.owned_process({"pid": os.getpid(), "identity": m.process_identity(os.getpid())}, tmp_path)


def test_installer_concurrent_operation_lock(tmp_path):
    import pytest
    with m.operation_lock(tmp_path):
        with pytest.raises(RuntimeError, match="in progress"):
            with m.operation_lock(tmp_path):
                pass


def test_installer_source_tree_manifest_is_git_compatible(tmp_path):
    import subprocess
    build_spec = importlib.util.spec_from_file_location("installer_builder", SOURCE.with_name("build.py"))
    builder = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(builder)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("example = 1\n")
    (tmp_path / "README.md").write_text("Example\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    expected = subprocess.check_output(["git", "-C", str(tmp_path), "write-tree"], text=True).strip()
    entries = []
    for path in (tmp_path / "src/a.py", tmp_path / "README.md"):
        data = path.read_bytes()
        entries.append({"path": str(path.relative_to(tmp_path)), "type": "blob", "mode": "100644", "sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
    assert builder.git_tree_digest(entries) == expected


def test_setup_preserves_keys_and_supports_space_paths(tmp_path):
    root = tmp_path / "MyAivan Server"
    m.check_root(root, initialize=True)
    for name in ("data", "logs", "run", "releases"):
        (root / name).mkdir()
    config = m.new_config(["tenant-a", "tenant-b"])
    sql = tmp_path / "sql.json"
    m.write_json(sql, {"version": 1, "databases": {name: {"url": f"mysql+{driver}://test@127.0.0.1/{name}"} for name, driver in (("aivan", "pymysql"), ("abcdyi", "aiomysql"), ("database", "pymysql"))}})
    config["database_config_file"] = str(sql)
    m.write_json(root / "config.json", config)
    with contextlib.redirect_stdout(io.StringIO()):
        m.main(["--prefix", str(root), "setup", "--origin", "https://myaivan.com", "--model-url", "http://127.0.0.1:11434", "--model-name", "configured-model", "--host-profile", "sin"])
    changed = m.read_json(root / "config.json")
    assert changed["tenants"] == config["tenants"]
    assert changed["secrets"] == config["secrets"]
    assert changed["model"]["name"] == "configured-model"
    assert changed["host_profile"] == "sin"


def test_setup_failed_restart_restores_configuration(tmp_path, monkeypatch):
    root = tmp_path / "server"
    m.check_root(root, initialize=True)
    (root / "run").mkdir()
    config = m.new_config(["tenant-a"])
    config["database_mode"] = "isolated"
    m.write_json(root / "config.json", config)
    monkeypatch.setattr(m, "status", lambda root: {"running": True})
    monkeypatch.setattr(m, "stop", lambda root: {"stopped": True})
    calls = []
    def start(root):
        calls.append(m.read_json(root / "config.json")["model"]["name"])
        if len(calls) == 1:
            raise RuntimeError("unavailable new endpoint")
        return {"ok": True}
    monkeypatch.setattr(m, "start", start)
    import pytest
    with pytest.raises(RuntimeError, match="unavailable"):
        m.main(["--prefix", str(root), "setup", "--model-name", "unavailable", "--restart"])
    assert m.read_json(root / "config.json") == config
    assert calls == ["unavailable", ""]


def test_self_extracting_entry_disables_bytecode_before_runtime(tmp_path):
    import subprocess
    import sys
    build_spec = importlib.util.spec_from_file_location("installer_entry_builder", SOURCE.with_name("build.py"))
    builder = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(builder)
    payload = tmp_path / "payload"
    (payload / "runtime/bin").mkdir(parents=True)
    # This unit-test interpreter shim is never included in a delivery artifact.
    interpreter = payload / "runtime/bin/python3"
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    interpreter.chmod(0o755)
    (payload / "runtime.py").write_text('import sys\nassert sys.dont_write_bytecode\nassert sys.flags.isolated\nprint("entry_flags_verified")\n')
    artifact = tmp_path / "installer.run"
    builder.write_installer(payload, artifact)
    result = subprocess.run(["sh", str(artifact), "--prefix", str(tmp_path / "with spaces")], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    assert "entry_flags_verified" in result.stdout


def test_self_extractor_rejects_traversal_before_execution(tmp_path):
    import subprocess
    import tarfile
    build_spec = importlib.util.spec_from_file_location("installer_archive_builder", SOURCE.with_name("build.py"))
    builder = importlib.util.module_from_spec(build_spec)
    build_spec.loader.exec_module(builder)
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "safe").write_text("safe")
    artifact = tmp_path / "installer.run"
    builder.write_installer(payload, artifact)
    original = artifact.read_bytes()
    prefix, original_payload = original.split(b"__MYAIVAN_PAYLOAD__\n", 1)
    malicious = tmp_path / "malicious.tar.gz"
    with tarfile.open(malicious, "w:gz") as archive:
        member = tarfile.TarInfo("../escape")
        member.size = 4
        archive.addfile(member, io.BytesIO(b"oops"))
    altered = malicious.read_bytes()
    prefix = prefix.replace(hashlib.sha256(original_payload).hexdigest().encode(), hashlib.sha256(altered).hexdigest().encode())
    artifact.write_bytes(prefix + b"__MYAIVAN_PAYLOAD__\n" + altered)
    result = subprocess.run(["sh", str(artifact), "--prefix", str(tmp_path / "install")], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Unsafe archive path" in result.stderr
    assert not (tmp_path / "install").exists()


def service_module():
    spec = importlib.util.spec_from_file_location("installer_service_test", SOURCE.with_name("service.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_user_service_unit_quotes_paths_without_secrets(tmp_path):
    service = service_module()
    text = service.unit_text(tmp_path / "server with spaces%name")
    assert 'with spaces%%name' in text
    assert ' -B -I ' in text
    assert ' serve\n' in text
    assert 'WantedBy=default.target' in text
    assert 'User=' not in text
    assert 'config.json' not in text
    assert 'API_KEY' not in text
    assert 'KillMode=control-group' in text


def test_unavailable_user_systemd_preserves_working_install(tmp_path, monkeypatch):
    import pytest
    service = service_module()
    monkeypatch.setattr(service, "systemctl", mock.Mock(side_effect=RuntimeError("unavailable")))
    stop = mock.Mock()
    with pytest.raises(RuntimeError, match="unavailable"):
        service.install(tmp_path, stop=stop, start=mock.Mock(), status=mock.Mock(), wait_healthy=mock.Mock(), write_json=m.write_json)
    stop.assert_not_called()
    assert not (tmp_path / "systemd.json").exists()


def test_current_user_service_install_and_remove(tmp_path, monkeypatch):
    service = service_module()
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "install space"
    root.mkdir()
    monkeypatch.setattr(service.Path, "home", lambda: home)
    commands = []
    monkeypatch.setattr(service, "systemctl", lambda *args: commands.append(args))
    stop = mock.Mock()
    result = service.install(root, stop=stop, start=mock.Mock(), status=lambda root: {"running": True}, wait_healthy=lambda root: {"ok": True}, write_json=m.write_json)
    name, _ = service.unit_identity(root)
    assert result["lingering_changed"] is False
    assert commands == [("show-environment",), ("daemon-reload",), ("enable", "--now", name)]
    assert (home / ".config/systemd/user" / name).is_file()
    service.uninstall(root, stop=stop)
    assert commands[-2:] == [("disable", "--now", name), ("daemon-reload",)]
    assert not (root / "systemd.json").exists()
    assert not (home / ".config/systemd/user" / name).exists()


def test_restart_routes_registered_installation_through_user_systemd(tmp_path, monkeypatch):
    config = m.new_config(["tenant-a"])
    config["database_mode"] = "isolated"
    m.write_json(tmp_path / "config.json", config)
    from types import SimpleNamespace
    (tmp_path / "systemd.json").write_text("{}")
    state = {"running": False}
    calls = []
    def start_registered(root):
        calls.append(root)
        state["running"] = True
    monkeypatch.setattr(m, "status", lambda root: state)
    monkeypatch.setattr(m, "stop", mock.Mock())
    monkeypatch.setattr(m, "load_service_module", lambda: SimpleNamespace(start_registered=start_registered))
    monkeypatch.setattr(m, "wait_healthy", lambda root: {"ok": True})
    with mock.patch.object(m.subprocess, "Popen") as daemon:
        assert m.start(tmp_path)["ok"]
        daemon.assert_not_called()
    assert calls == [tmp_path]


def test_user_service_start_revalidates_owned_unit(tmp_path, monkeypatch):
    service = service_module()
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(service.Path, "home", lambda: home)
    commands = []
    monkeypatch.setattr(service, "systemctl", lambda *args: commands.append(args))
    name, marker = service.unit_identity(root)
    unit = home / ".config/systemd/user" / name
    unit.parent.mkdir(parents=True)
    unit.write_text(service.unit_text(root))
    m.write_json(root / "systemd.json", {"unit": name, "path": str(unit)})
    service.start_registered(root)
    assert commands == [("start", name)]
    unit.write_text("# A different application\n")
    import pytest
    with pytest.raises(ValueError, match="replaced"):
        service.start_registered(root)
    assert commands == [("start", name)]


def test_registered_failed_health_stops_services_before_upgrade_restore(tmp_path, monkeypatch):
    config = m.new_config(["tenant-a"])
    config["database_mode"] = "isolated"
    m.write_json(tmp_path / "config.json", config)
    from types import SimpleNamespace
    import pytest
    (tmp_path / "systemd.json").write_text("{}")
    running = {"value": False}
    def registered(root):
        running["value"] = True
    monkeypatch.setattr(m, "status", lambda root: {"running": running["value"]})
    stop = mock.Mock()
    monkeypatch.setattr(m, "stop", stop)
    monkeypatch.setattr(m, "load_service_module", lambda: SimpleNamespace(start_registered=registered))
    monkeypatch.setattr(m, "wait_healthy", mock.Mock(side_effect=RuntimeError("unhealthy release")))
    with pytest.raises(RuntimeError, match="unhealthy"):
        m.start(tmp_path)
    assert stop.call_count == 2


def test_five_service_upgrade_preserves_credentials_and_execution_identity():
    legacy = m.new_config(['tenant-a', 'tenant-b'])
    legacy['version'] = 1
    legacy['ports'].pop('abcdyi')
    legacy['secrets'].pop('abcdyi')
    legacy.pop('fulfillment')
    m.validate_config(legacy)
    upgraded = m.upgrade_config(legacy)
    m.validate_config(upgraded)
    assert upgraded['tenants'] == legacy['tenants']
    assert all(upgraded['ports'][key] == value for key, value in legacy['ports'].items())
    assert all(upgraded['secrets'][key] == value for key, value in legacy['secrets'].items())
    assert m.upgrade_config(upgraded) == upgraded
    identities = upgraded['fulfillment']['tenants']
    assert identities['tenant-a']['tenant_id'] != identities['tenant-b']['tenant_id']
    assert identities['tenant-a']['operator_id'] != identities['tenant-b']['operator_id']


def test_five_service_rollback_preserves_sixth_service_identity_for_reupgrade(tmp_path):
    config = m.new_config(['tenant-a'])
    config["database_mode"] = "isolated"
    old = tmp_path / 'old-release'; old.mkdir()
    (old / 'manifest.json').write_text(json.dumps({'components': {'aivan': {}}}))
    rolled_back = m.config_for_release(config, old)
    m.validate_config(rolled_back)
    assert rolled_back['version'] == 1
    assert 'abcdyi' not in rolled_back['ports']
    assert rolled_back['fulfillment'] == config['fulfillment']
    assert m.upgrade_config(rolled_back) == config


def test_fulfillment_provider_tenant_mapping_and_jwt_secret_are_independent(tmp_path):
    config = m.new_config(['tenant-a', 'tenant-b'])
    config["database_mode"] = "isolated"
    (tmp_path / 'manifest.json').write_text(json.dumps({'components': {'aivan': {'revision': 'a' * 40}}}))
    env = m.environment(tmp_path, tmp_path, config)
    mapping = json.loads(env['ABCDYI_PRIVATE_DATA_TENANT_MAP'])
    assert set(mapping.values()) == {'tenant-a', 'tenant-b'}
    assert env['SECRET_KEY'] != config['secrets']['database']
    assert env['DATABASE_URL'].startswith('sqlite+aiosqlite:///')
    assert json.loads(env['MYAIVAN_FULFILLMENT_API_KEYS']) == config['tenants']


def test_invalid_fulfillment_identity_mapping_is_rejected():
    config = m.new_config(['tenant-a', 'tenant-b'])
    config['fulfillment']['tenants']['tenant-b'] = config['fulfillment']['tenants']['tenant-a']
    import pytest
    with pytest.raises(ValueError, match='identities'):
        m.validate_config(config)


def test_builder_keeps_independent_abcdyi_source_out_of_shared_wheels():
    source = SOURCE.with_name('build.py').read_text()
    launcher = SOURCE.with_name('abcdyi_service.py').read_text()
    assert 'if component == "abcdyi"' in source
    assert 'payload / "services/abcdyi"' in source
    assert 'sys.path.insert(0, str(root))' in launcher
    assert 'sys.path.insert(0, str(root /' not in launcher


def test_payload_inventory_rejects_unlisted_fifo(tmp_path):
    import os
    import pytest
    payload = tmp_path / 'payload'; payload.mkdir()
    (payload / 'manifest.json').write_text(json.dumps({'files': {}}))
    os.mkfifo(payload / 'unlisted-pipe')
    with pytest.raises(ValueError, match='nonregular'):
        m.verify_payload(payload)


def test_configuration_rejects_non_header_safe_credentials():
    import pytest
    for value in ('é' * 32, 'a' * 31 + '\n', 'a' * 31 + ' '):
        config = m.new_config(['tenant-a'])
        config['tenants']['tenant-a'] = value
        with pytest.raises(ValueError, match='credentials'):
            m.validate_config(config)


def test_build_git_pin_rejects_links_and_false_revision(tmp_path):
    import subprocess
    import pytest
    spec = importlib.util.spec_from_file_location('build_safety_review', SOURCE.with_name('build.py'))
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    root = tmp_path / 'source'; (root / 'src').mkdir(parents=True)
    outside = tmp_path / 'outside.py'; outside.write_text('synthetic = 1\n')
    (root / 'src/foreign.py').symlink_to(outside)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Synthetic source'], check=True)
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    with pytest.raises(ValueError, match='revision'):
        builder.source_evidence(root, 'a' * 40, tree)
    with pytest.raises(ValueError, match='links'):
        builder.source_evidence(root, revision, tree)


def test_external_store_change_requires_explicit_logical_identity(tmp_path):
    import pytest
    root = tmp_path / 'server'; m.check_root(root, initialize=True)
    for name in ('data', 'logs', 'run', 'releases'): (root / name).mkdir()
    config = m.new_config(['tenant-a'])
    config["database_mode"] = "isolated"
    m.write_json(root / 'config.json', config)
    with pytest.raises(ValueError, match='database-provider-id'):
        m.main(['--prefix', str(root), 'setup', '--database-url', 'https://private-db.invalid'])
    assert m.read_json(root / 'config.json') == config
    with contextlib.redirect_stdout(io.StringIO()):
        m.main(['--prefix', str(root), 'setup', '--database-url', 'https://private-db.invalid', '--database-provider-id', 'another-private-store'])
    external = m.read_json(root / 'config.json')
    assert external['private_data_provider_id'] == 'another-private-store'
    assert external['tenants'] == config['tenants']
    with contextlib.redirect_stdout(io.StringIO()):
        m.main(['--prefix', str(root), 'setup', '--database-url', ''])
    assert m.read_json(root / 'config.json')['private_data_provider_id'] == config['private_data_provider_id']


def test_build_rejects_untracked_migration_and_runtime_assets(tmp_path):
    import subprocess
    import pytest
    spec = importlib.util.spec_from_file_location('build_asset_guard', SOURCE.with_name('build.py'))
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    root = tmp_path / 'source'; root.mkdir()
    (root / 'README.md').write_text('Synthetic source fixture\n')
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Synthetic source'], check=True)
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
    assert builder.source_evidence(root, revision, tree)['modified'] is False
    for name in ('src/new.py', 'api/new.py', 'alembic/versions/new.py', 'generators/new.py', 'scripts/migration.py', 'installer/configuration.py'):
        asset = root / name; asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text('synthetic = True\n')
        with pytest.raises(ValueError, match='Untracked application runtime'):
            builder.source_evidence(root, revision, tree)
        asset.unlink()
