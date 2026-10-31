"""Migration planning must isolate every configured component's physical store."""
import importlib.util
from pathlib import Path

import pytest


def installer():
    path = Path(__file__).parents[1] / 'installer/databases.py'
    spec = importlib.util.spec_from_file_location('migration_namespace_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_plan(monkeypatch, module):
    targets = {name: {'url': 'mysql+pymysql://synthetic@' + host + '/shared',
                     'schema': 'shared', 'engine': 'mysql'}
               for name, host in [('aivan', 'localhost'), ('abcdyi', '127.0.0.1')]}
    monkeypatch.setattr(module.RUNTIME, 'verify_payload', lambda *a: {'release': 'synthetic', 'components': {}})
    monkeypatch.setattr(module.RUNTIME, 'read_json', lambda *a: {'database_mode': 'external'})
    monkeypatch.setattr(module.RUNTIME, 'validate_config', lambda *a: None)
    monkeypatch.setattr(module.CONFIG, 'configured_targets', lambda *a: targets)
    return targets


def test_selected_component_cannot_skip_other_physical_namespace(monkeypatch, tmp_path):
    module = installer()
    targets = configured_plan(monkeypatch, module)
    monkeypatch.setattr(module, 'HERE', tmp_path)
    (tmp_path / 'manifest.json').write_text('{}')
    probes = []
    inspections = []
    def verify_all(selected):
        probes.append(set(selected))
        if set(selected) == {'aivan', 'abcdyi'}:
            raise RuntimeError('The connected applications share a physical database namespace')
    monkeypatch.setattr(module.CONFIG, 'verify_physical_namespaces', verify_all)
    monkeypatch.setattr(module, 'inspect_target', lambda *a: inspections.append(a) or {'namespace_sha256': 'same'})
    # No package file should be needed: collision must fail before selected schema inspection.
    with pytest.raises((ValueError, RuntimeError), match='physical.*namespace'):
        module.plan(tmp_path, ['aivan'])
    assert probes == [set(targets)]
    assert inspections == []


def test_physical_probe_failure_stops_before_selected_migration(monkeypatch, tmp_path):
    module = installer()
    configured_plan(monkeypatch, module)
    def fail(targets):
        raise RuntimeError('Synthetic unrelated-target connectivity failure')
    monkeypatch.setattr(module.CONFIG, 'verify_physical_namespaces', fail)
    calls = []
    monkeypatch.setattr(module, 'apply_component', lambda *a, **kw: calls.append(a))
    with pytest.raises((RuntimeError, ValueError)):
        module.migrate(tmp_path, {}, components=['aivan'], tenant='tenant-a', authorization='test', backup='test')
    assert calls == []


def test_all_targets_are_verified_but_only_selected_schema_is_planned(monkeypatch, tmp_path):
    module = installer()
    targets = configured_plan(monkeypatch, module)
    monkeypatch.setattr(module, 'HERE', tmp_path)
    (tmp_path / 'manifest.json').write_text('{}')
    probes, inspections = [], []
    monkeypatch.setattr(module.CONFIG, 'verify_physical_namespaces', lambda values: probes.append(set(values)))
    monkeypatch.setattr(module, 'inspect_target', lambda name, target: inspections.append(name) or {'namespace_sha256': name})
    result = module.plan(tmp_path, ['aivan'])
    assert probes == [set(targets)]
    assert inspections == ['aivan']
    assert set(result['components']) == {'aivan'}
