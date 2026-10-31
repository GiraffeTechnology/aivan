"""A fixed gpm tenant profile must not widen the one-source integrity engine."""
import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_myaivan_ui_outcome_builder import selection


FIELDS = ('BASE_SHA256', 'BASE_REVISION', 'BASE_TREE', 'UI_SOURCE', 'UI_TARGET', 'BUILD_KIND', 'PROFILE_SHA256')


def builder():
    directory = Path(__file__).resolve().parents[1] / 'installer'
    path = directory / 'build_gpm_tenant_successor.py'
    assert path.is_file(), 'the bounded gpm_tenant successor profile is not implemented'
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('gpm_tenant_successor_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_profile_and_restoration():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with module.gpm_tenant_profile() as engine:
        assert engine.BASE_SHA256 == '3beef41ca931f6254a6aad555dfd1ef353e0cebfda4b07eff4a10d8946d95e94'
        assert engine.BASE_REVISION == '00636c8ad45f2485dc05245835013529fbaf75f9'
        assert engine.BASE_TREE == '0b159a6073ae873620b44d5b1af609d0f42ccfd4'
        assert engine.UI_SOURCE == 'src/aivan/execution/gpm_guidance.py'
        assert engine.UI_TARGET.endswith('/aivan/execution/gpm_guidance.py')
        assert engine.BUILD_KIND == 'offline-gpm-tenant-successor'
        assert engine.PROFILE_SHA256 == engine.build.digest(Path(module.__file__))
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_profile_restores_engine_after_failure():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with pytest.raises(RuntimeError, match='synthetic'):
        with module.gpm_tenant_profile():
            raise RuntimeError('synthetic build failure')
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_facade_is_the_only_selected_runtime_delta(tmp_path):
    module = builder()
    with module.gpm_tenant_profile() as engine:
        source, manifest = selection(tmp_path, engine)
        selected = engine.verify_selection(source, manifest)
        assert selected['source_path'] == 'src/aivan/execution/gpm_guidance.py'
        assert selected['candidate_sha256'] == engine.build.digest(source / engine.UI_SOURCE)


@pytest.mark.parametrize('name', ['src/aivan/app/static/app.js', 'src/aivan/integrations/gltg.py',
                               'alembic/versions/change.py', 'installer/runtime.py', 'installer/requirements.lock'])
def test_profile_rejects_unselected_changes(tmp_path, name):
    module = builder()
    with module.gpm_tenant_profile() as engine:
        source, manifest = selection(tmp_path, engine)
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original pinned bytes')
        manifest['components']['aivan']['verified_build_input_files'] = {name: engine.build.digest(path)}
        path.write_bytes(b'unselected change')
        with pytest.raises(ValueError):
            engine.verify_selection(source, manifest)


def test_wrong_base_is_rejected_before_extraction(tmp_path):
    module = builder()
    artifact = tmp_path / 'wrong-base.run'
    artifact.write_bytes(b'not the pinned order installer')
    destination = tmp_path / 'payload'
    destination.mkdir()
    with module.gpm_tenant_profile() as engine:
        with pytest.raises(ValueError, match='checksum'):
            engine.extract_base(artifact, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('failure', [False, True])
def test_entrypoint_uses_profile_and_restores_defaults(monkeypatch, failure):
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    called = []
    def invoke(*, description):
        called.append(description)
        assert module.engine.UI_SOURCE == 'src/aivan/execution/gpm_guidance.py'
        assert module.engine.BUILD_KIND == 'offline-gpm-tenant-successor'
        if failure:
            raise ValueError('synthetic entrypoint failure')
    monkeypatch.setattr(module.engine, 'main', invoke)
    if failure:
        with pytest.raises(ValueError, match='synthetic'):
            module.main()
    else:
        module.main()
    assert len(called) == 1 and 'gpm tenant' in called[0].lower()
    assert {key: getattr(module.engine, key) for key in FIELDS} == original
