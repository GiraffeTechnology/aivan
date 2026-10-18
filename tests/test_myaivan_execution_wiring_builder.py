"""Bounded packaging unit fixtures; never installation or native-runtime QA."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


def builder():
    directory = Path(__file__).resolve().parents[1] / 'installer'
    path = directory / 'build_execution_wiring_successor.py'
    assert path.is_file(), 'execution wiring packaging is not implemented'
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('execution_wiring_builder', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected(tmp_path, module):
    source, payload = tmp_path / 'source', tmp_path / 'payload'
    source.mkdir(); payload.mkdir()
    changes = []
    for name, target in module.source_targets().items():
        candidate, installed = source / name, payload / target
        candidate.parent.mkdir(parents=True, exist_ok=True)
        installed.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(('synthetic candidate ' + name).encode())
        installed.write_bytes(b'synthetic baseline')
        changes.append({'source_path': name, 'target': target,
                        'base_sha256': hashlib.sha256(installed.read_bytes()).hexdigest(),
                        'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest()})
    return source, payload, changes


def test_fixed_base_source_and_bounded_targets():
    m = builder()
    assert m.BASE_SHA256 == 'c08be0645a38dabec08520a3717035889be04b8ea2be3f1f36fe9a456b2b9e62'
    assert m.BASE_REVISION == '22bdf78f393dc8e1a16483280cdf6bfeb019c236'
    assert m.SOURCE_REVISION == '6707c2b1e73b59fdceac5184e9b561fdd69e9919'
    assert m.SOURCE_TREE == 'c8e3ec4ffa6444d5a0df4703f10b7514fb7c221d'
    assert len(m.source_targets()) == 12
    assert m.source_targets()['installer/runtime.py'] == 'runtime.py'
    assert all('gpm_guidance.py' not in path and 'gltg.py' not in path for path in m.source_targets())


@pytest.mark.parametrize('revision,tree', [('f' * 40, 'f' * 40), ('short', 'f' * 40)])
def test_wrong_candidate_identity_rejected(revision, tree):
    m = builder()
    with pytest.raises(ValueError):
        m.assert_candidate_identity(revision, tree)


@pytest.mark.parametrize('name', ['src/aivan/integrations/gltg.py', 'src/aivan/execution/gpm_guidance.py',
    'installer/requirements.lock', 'alembic/versions/change.py', 'src/aivan/api/../escape.py'])
def test_unselected_source_changes_rejected(name):
    m = builder()
    paths = {path: 'M' for path in m.source_targets()}
    paths[name] = 'M'
    with pytest.raises(ValueError):
        m.validate_changes(paths)


@pytest.mark.parametrize('status', ['D', 'R100', 'T'])
def test_deletion_rename_and_type_changes_rejected(status):
    m = builder()
    paths = {path: 'M' for path in m.source_targets()}
    paths['src/aivan/app/static/app.js'] = status
    with pytest.raises(ValueError):
        m.validate_changes(paths)


def test_overlay_changes_only_fixed_targets_and_preserves_native_bytes(tmp_path):
    m = builder()
    source, payload, changes = selected(tmp_path, m)
    native = payload / 'runtime/bin/python3'
    native.parent.mkdir(parents=True)
    native.write_bytes(b'\x7fELF synthetic non-executable fixture')
    before = native.read_bytes()
    m.apply_files(source, payload, changes)
    for item in changes:
        assert (payload / item['target']).read_bytes() == (source / item['source_path']).read_bytes()
    assert native.read_bytes() == before


@pytest.mark.parametrize('change', ['source', 'installed', 'target', 'symlink'])
def test_overlay_rejects_changed_inputs_or_unselected_target(tmp_path, change):
    m = builder()
    source, payload, changes = selected(tmp_path, m)
    first = changes[0]
    if change == 'source':
        (source / first['source_path']).write_bytes(b'changed after selection')
    elif change == 'installed':
        (payload / first['target']).write_bytes(b'changed baseline')
    elif change == 'target':
        first['target'] = '../escape.py'
    else:
        path = source / first['source_path']
        path.unlink()
        path.symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError):
        m.apply_files(source, payload, changes)


def test_base_extraction_restores_existing_engine_on_failure(tmp_path):
    m = builder()
    fields = ('BASE_SHA256', 'BASE_REVISION', 'BASE_TREE', 'UI_SOURCE', 'UI_TARGET')
    before = {key: getattr(m.engine, key) for key in fields}
    bad = tmp_path / 'bad.run'
    bad.write_bytes(b'not the selected installer')
    with pytest.raises(ValueError, match='checksum'):
        m.extract_base(bad, tmp_path / 'payload')
    assert {key: getattr(m.engine, key) for key in fields} == before


@pytest.mark.parametrize('change', ['none', 'hash', 'upstream', 'path'])
def test_asset_manifest_hashes_and_origin_are_checked(tmp_path, change):
    m = builder()
    static = tmp_path / 'src/aivan/app/static'
    static.mkdir(parents=True)
    assets = {}
    for name in m.ASSET_NAMES:
        data = ('synthetic asset ' + name).encode()
        (static / name).write_bytes(data)
        assets[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = {'upstream_repository': 'GiraffeTechnology/abcdYi',
                'upstream_commit': m.ASSET_REVISION, 'assets': assets}
    if change == 'hash':
        assets[next(iter(assets))]['sha256'] = '0' * 64
    elif change == 'upstream':
        manifest['upstream_commit'] = '0' * 40
    elif change == 'path':
        assets['../escape.js'] = assets.pop(next(iter(assets)))
    (static / 'r6-execution-assets.json').write_text(json.dumps(manifest))
    if change == 'none':
        assert m.verify_assets(tmp_path)['upstream_commit'] == m.ASSET_REVISION
    else:
        with pytest.raises(ValueError):
            m.verify_assets(tmp_path)


@pytest.mark.parametrize('kind', ['overwrite', 'inside-source'])
def test_entrypoint_preserves_retained_artifacts_and_source(tmp_path, monkeypatch, kind):
    m = builder()
    source, output = tmp_path / 'source', tmp_path / 'output'
    source.mkdir(); output.mkdir()
    existing = output / 'myaivan-unit-release-linux-x86_64.run'
    existing.write_bytes(b'retained artifact fixture')
    if kind == 'inside-source':
        output = source / 'output'
    monkeypatch.setattr(sys, 'argv', ['build_execution_wiring_successor.py',
        '--base-installer', str(tmp_path / 'not-read.run'), '--source', str(source), '--output', str(output),
        '--revision', m.SOURCE_REVISION, '--tree', m.SOURCE_TREE, '--release', 'unit-release'])
    with pytest.raises(ValueError):
        m.main()
    assert existing.read_bytes() == b'retained artifact fixture'
