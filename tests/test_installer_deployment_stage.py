"""Stage selection must prevent fulfillment side effects, not fake readiness."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('stage_test_' + name, ROOT / 'installer' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = module('runtime')
database = module('database_config')
deployment = module('deployment_config')
healthcheck = module('healthcheck')


def config(stage='aivan'):
    value = runtime.new_config(['tenant-a'])
    value.update(deployment_stage=stage, database_mode='external')
    value['external']['database'] = 'https://provider.example'
    return value


def private(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return str(path)


def sql_config(tmp_path, value, include_fulfillment=False):
    targets = {'aivan': {'url': 'mysql+pymysql://synthetic@sql.example/aivan'}}
    if include_fulfillment:
        targets['abcdyi'] = {'url': 'mysql+aiomysql://synthetic@deferred.example/fulfillment'}
    value['database_config_file'] = private(tmp_path / 'sql.json', {'version': 1, 'databases': targets})
    return targets


@pytest.mark.parametrize('include_fulfillment', [False, True])
def test_deferred_sql_has_no_fulfillment_connection_target(tmp_path, include_fulfillment):
    value = config()
    sql_config(tmp_path, value, include_fulfillment)
    assert set(database.configured_targets(value, tmp_path)) == {'aivan'}
    assert set(json.loads(Path(value['database_config_file']).read_text())['databases']) == (
        {'aivan', 'abcdyi'} if include_fulfillment else {'aivan'})


def test_activation_restores_required_descriptor_and_namespace_checks(tmp_path):
    value = config('integrated')
    sql_config(tmp_path, value)
    with pytest.raises(ValueError, match='distinct'):
        database.configured_targets(value, tmp_path)
    targets = sql_config(tmp_path, value, True)
    assert set(database.configured_targets(value, tmp_path)) == {'aivan', 'abcdyi'}
    targets['abcdyi']['url'] = 'mysql+aiomysql://synthetic@sql.example/aivan'
    private(Path(value['database_config_file']), {'version': 1, 'databases': targets})
    with pytest.raises(ValueError, match='distinct'):
        database.configured_targets(value, tmp_path)


@pytest.mark.parametrize('stage', [None, '', 'disabled', False, 1])
def test_unknown_stage_fails_closed(stage, tmp_path):
    value = config(stage)
    with pytest.raises(ValueError, match='stage'):
        runtime.validate_config(value)
    with pytest.raises(ValueError, match='stage'):
        database.configured_targets(value, tmp_path)
    with pytest.raises(ValueError, match='stage'):
        healthcheck.probe(value, runtime.SERVICES, {})


def test_profile_stage_change_preserves_tenants_secrets_and_ports():
    value = config('integrated')
    result = deployment.profile(value, {'version': 1, 'deployment_stage': 'aivan'},
                                endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants)
    runtime.validate_config(result)
    for key in ('ports', 'fulfillment', 'tenants', 'secrets'):
        assert result[key] == value[key]
    assert value['deployment_stage'] == 'integrated'
    with pytest.raises(ValueError, match='stage'):
        deployment.profile(value, {'version': 1, 'deployment_stage': 'typo'},
                           endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants)


def test_environment_and_published_ports_do_not_advertise_deferred_service(tmp_path, monkeypatch):
    value = config()
    sql_config(tmp_path, value, True)
    value['service_credentials_file'] = private(tmp_path / 'auth.json', {
        'version': 1, 'services': {'database': {'service_auth': 'synthetic-secret'}}})
    (tmp_path / 'manifest.json').write_text(json.dumps({'components': {'aivan': {'revision': 'a' * 40}}}))
    # An ambient stale environment must not leak into the subprocess environment.
    monkeypatch.setenv('DATABASE_URL', 'forbidden-ambient-value')
    monkeypatch.setenv('MYAIVAN_EXECUTION_BASE_URL', 'http://127.0.0.1:12345')
    env = runtime.environment(tmp_path, tmp_path, value)
    for key in ('DATABASE_URL', 'SECRET_KEY', 'MYAIVAN_EXECUTION_BASE_URL',
                'MYAIVAN_FULFILLMENT_TENANTS', 'MYAIVAN_FULFILLMENT_API_KEYS'):
        assert key not in env
    assert env['MYAIVAN_DEPLOYMENT_STAGE'] == 'aivan'
    assert env['AIVAN_REQUIRE_HUMAN_APPROVAL'] == 'true'
    assert env['AIVAN_DB_URL'].endswith('/aivan')
    assert env['GIRAFFE_DB_SERVICE_AUTH_SECRET'] == 'synthetic-secret'
    assert {'web', 'gltg', 'gpm', 'language'} <= set(runtime.active_services(value))
    assert 'abcdyi' not in runtime.active_services(value)
    runtime.publish_ports(tmp_path, value)
    published = json.loads((tmp_path / 'run/ports.json').read_text())
    assert 'abcdyi' not in published['services']
    assert published['fulfillment_status'] == 'not_deployed'
    value['deployment_stage'] = 'integrated'
    restored = runtime.environment(tmp_path, tmp_path, value)
    assert restored['DATABASE_URL'].endswith('/fulfillment')
    assert restored['MYAIVAN_FULFILLMENT_API_KEYS'] == json.dumps(value['tenants'])
    assert 'abcdyi' in runtime.active_services(value)


def test_deferred_health_is_explicit_and_never_requests_fulfillment(monkeypatch):
    value = config()
    request = Mock(return_value={'status': 'ok'})
    monkeypatch.setattr(healthcheck, 'request_json', request)
    result = healthcheck.probe(value, {'abcdyi': runtime.SERVICES['abcdyi']}, {})
    assert result['abcdyi'] == {'ok': False, 'required': False, 'status': 'not_deployed'}
    request.assert_not_called()
    value['deployment_stage'] = 'integrated'
    result = healthcheck.probe(value, {'abcdyi': runtime.SERVICES['abcdyi']}, {})
    assert result['abcdyi']['ok'] is True
    request.assert_called_once()


@pytest.mark.parametrize('stage,expected', [('aivan', {'aivan'}), ('integrated', {'aivan', 'abcdyi'})])
def test_bootstrap_connects_and_launches_only_selected_targets(tmp_path, monkeypatch, stage, expected):
    # Bundled provider imports are not needed for this external-provider path.
    # These are unit isolation doubles, not real provider/SQL acceptance.
    import sys
    from types import ModuleType
    for name, attribute in [('giraffe_db.db.base', 'Base'), ('giraffe_db.db.models.core', 'Tenant')]:
        stub = ModuleType(name)
        setattr(stub, attribute, object)
        monkeypatch.setitem(sys.modules, name, stub)
    bootstrap = module('bootstrap')
    value = config(stage)
    sql_config(tmp_path, value, True)
    (tmp_path / 'config.json').write_text(json.dumps(value))
    probes = []
    helpers = SimpleNamespace(
        configured_targets=database.configured_targets,
        verify_physical_namespaces=lambda targets: probes.append(set(targets)),
        verify_namespace=Mock(), require_schema=Mock())
    monkeypatch.setattr(bootstrap, 'database_helpers', lambda: helpers)
    monkeypatch.setattr(bootstrap, 'create_engine', Mock(return_value=Mock()))
    monkeypatch.setattr(bootstrap, 'inspect', Mock(return_value=SimpleNamespace(get_table_names=lambda: ['existing'])))
    monkeypatch.setattr(bootstrap, 'require_current_schema', Mock())
    launch = Mock()
    monkeypatch.setattr(bootstrap.subprocess, 'run', launch)
    monkeypatch.setenv('AIVAN_DB_URL', 'mysql+pymysql://synthetic@sql.example/aivan')
    bootstrap.initialize(tmp_path)
    assert probes == [expected]
    assert launch.call_count == (1 if stage == 'integrated' else 0)
    if stage == 'integrated':
        assert launch.call_args.args[0][-2:] == ['bootstrap', str(tmp_path)]


def test_deferred_migration_cannot_select_fulfillment(tmp_path, monkeypatch):
    migrations = module('databases')
    value = config()
    sql_config(tmp_path, value, True)
    monkeypatch.setattr(migrations.RUNTIME, 'verify_payload', lambda *a: {'release': 'synthetic', 'components': {}})
    monkeypatch.setattr(migrations.RUNTIME, 'read_json', lambda *a: value)
    probe = Mock()
    monkeypatch.setattr(migrations.CONFIG, 'verify_physical_namespaces', probe)
    with pytest.raises(ValueError, match='Select configured'):
        migrations.plan(tmp_path, ['abcdyi'])
    probe.assert_not_called()
    monkeypatch.setattr(migrations, 'HERE', tmp_path)
    (tmp_path / 'manifest.json').write_text('{}')
    monkeypatch.setattr(migrations, 'inspect_target', lambda name, target: {'namespace_sha256': name})
    plan = migrations.plan(tmp_path, ['aivan'])
    assert plan['deployment_stage'] == 'aivan'
    assert set(probe.call_args.args[0]) == {'aivan'}
    assert set(plan['components']) == {'aivan'}


def test_default_integrated_and_rollback_capability_are_preserved(tmp_path):
    value = config('integrated')
    value.pop('deployment_stage')
    assert runtime.fulfillment_enabled(value)
    runtime.require_stage_support(value, {})
    value['deployment_stage'] = 'aivan'
    with pytest.raises(RuntimeError, match='cannot preserve'):
        runtime.require_stage_support(value, {})
    runtime.require_stage_support(value, {'deployment_stages': ['aivan', 'integrated']})
    (tmp_path / 'manifest.json').write_text(json.dumps({'components': {'abcdyi': {}}, 'files': {}}))
    with pytest.raises(RuntimeError, match='cannot preserve.*stage'):
        runtime.config_for_release(value, tmp_path)


@pytest.mark.parametrize('command', ['bootstrap', 'serve', 'buyer-create'])
def test_direct_fulfillment_entry_rejects_deferred_stage_before_import(monkeypatch, command):
    fulfillment = module('abcdyi_service')
    monkeypatch.setenv('MYAIVAN_DEPLOYMENT_STAGE', 'aivan')
    monkeypatch.setattr('sys.argv', ['abcdyi_service.py', command])
    source = Mock(side_effect=AssertionError('must not load fulfillment source'))
    monkeypatch.setattr(fulfillment, 'load_source', source)
    with pytest.raises(RuntimeError, match='not enabled'):
        fulfillment.main()
    source.assert_not_called()


def test_operator_prompts_only_for_active_sql_targets(tmp_path, monkeypatch):
    operator = module('operator_setup')
    value = config()
    monkeypatch.setattr(operator, 'require_terminal', lambda: None)
    prompted = []
    monkeypatch.setattr(operator, 'mysql_descriptor', lambda name, driver: prompted.append(name) or {
        'url': 'mysql+pymysql://synthetic@sql.example/' + name})
    result = operator.configure_databases(value, tmp_path / 'operator.json', validator=database.sql_target)
    assert prompted == ['aivan']
    assert result['database_targets'] == 1


def test_supervisor_never_spawns_deferred_fulfillment(tmp_path, monkeypatch):
    value = config()
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'run').mkdir()
    monkeypatch.setattr(runtime, 'release', lambda root: tmp_path)
    monkeypatch.setattr(runtime, 'read_json', lambda path: value)
    monkeypatch.setattr(runtime, 'write_json', lambda *a: None)
    monkeypatch.setattr(runtime, 'publish_ports', lambda *a: None)
    monkeypatch.setattr(runtime, 'environment', lambda *a: {'MYAIVAN_DEPLOYMENT_STAGE': 'aivan'})
    monkeypatch.setattr(runtime, 'process_identity', lambda pid: 'synthetic')
    monkeypatch.setattr(runtime.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(runtime, 'bind_available_port', lambda requested, reserved, used: (
        SimpleNamespace(fileno=lambda: 7, close=lambda: None), requested))
    launches = []
    def spawn(command, **kwargs):
        launches.append(command)
        return SimpleNamespace(pid=123, poll=lambda: None, terminate=lambda: None, wait=lambda **kw: None)
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    class EndTick(Exception):
        pass
    def end_tick(_seconds):
        raise EndTick()
    monkeypatch.setattr(runtime.time, 'sleep', end_tick)
    with pytest.raises(EndTick):
        runtime._supervise(tmp_path)
    assert len(launches) == len(runtime.active_services(value))
    assert len(launches) > 0
    assert all(not any('abcdyi_service.py' in str(arg) for arg in command) for command in launches)


@pytest.mark.parametrize('ready', [True, False])
def test_stage_readiness_does_not_hide_required_service_failure(tmp_path, monkeypatch, ready):
    value = config()
    (tmp_path / 'config.json').write_text(json.dumps(value))
    monkeypatch.setattr(runtime, 'status', lambda root: {'running': True})
    monkeypatch.setattr(runtime, 'load_deployment_module', lambda: SimpleNamespace(
        validate=lambda *a, **kw: None,
        credentials=lambda *a: {'database': {'service_auth': 'synthetic'}},
        stage=lambda c: c['deployment_stage']))
    # Keep the real health probe: network is stubbed at its urllib boundary.
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            return json.dumps({'status': 'ok' if ready else 'not_ready', 'ready': ready,
                               'giraffe_db': 'ok', 'persistence_enabled': True,
                               'packet_persistence': 'durable', 'tenant_id': 'tenant-a'}).encode()
    import urllib.request
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: SimpleNamespace(open=lambda *a, **kw: Response()))
    result = runtime.health(tmp_path)
    assert result['ok'] is ready
    assert result['deployment_stage'] == 'aivan'
    assert result['services']['abcdyi']['status'] == 'not_deployed'
    assert result['services']['abcdyi']['ok'] is False


def test_missing_provider_auth_is_still_rejected(tmp_path):
    value = config()
    sql_config(tmp_path, value)
    (tmp_path / 'manifest.json').write_text(json.dumps({'components': {'aivan': {'revision': 'a' * 40}}}))
    with pytest.raises(ValueError, match='credentials are required'):
        runtime.environment(tmp_path, tmp_path, value)


def test_installer_buyer_command_rejects_before_subprocess(tmp_path, monkeypatch):
    from contextlib import nullcontext
    value = config()
    monkeypatch.setattr('sys.argv', ['runtime.py', '--prefix', str(tmp_path), 'buyer-create',
                                   '--tenant', 'tenant-a', '--email', 'buyer@example.invalid', '--full-name', 'Buyer'])
    monkeypatch.setattr(runtime, 'check_root', lambda *a, **kw: None)
    monkeypatch.setattr(runtime, 'operation_lock', lambda *a: nullcontext())
    monkeypatch.setattr(runtime, 'release', lambda *a: tmp_path)
    monkeypatch.setattr(runtime, 'verify_payload', lambda *a: {})
    monkeypatch.setattr(runtime, 'read_json', lambda *a: value)
    launch = Mock()
    monkeypatch.setattr(runtime.subprocess, 'run', launch)
    with pytest.raises(RuntimeError, match='explicitly enabled'):
        runtime.main()
    launch.assert_not_called()
