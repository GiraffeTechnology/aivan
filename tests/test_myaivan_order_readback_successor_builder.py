"""A fixed order readback profile must not widen the one-source integrity engine."""
import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_myaivan_ui_outcome_builder import selection


FIELDS = ('BASE_SHA256', 'BASE_REVISION', 'BASE_TREE', 'UI_SOURCE', 'UI_TARGET', 'BUILD_KIND', 'PROFILE_SHA256')


def builder():
    directory = Path(__file__).resolve().parents[1] / 'installer'
    path = directory / 'build_gltg_order_readback_successor.py'
    assert path.is_file(), 'the bounded order_readback successor profile is not implemented'
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('order_readback_successor_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_profile_and_restoration():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with module.order_readback_profile() as engine:
        assert engine.BASE_SHA256 == 'e2b39884b7af6a2f654cacbd5713d9c30d89f3ddd004a1098d865e9f05e2265d'
        assert engine.BASE_REVISION == '4e66685f8594394cdd7ab81695ba4c658b0f6c82'
        assert engine.BASE_TREE == '11792a215427b49ae607531c943bf564b16bc4e2'
        assert engine.UI_SOURCE == 'src/aivan/integrations/order_confirmation.py'
        assert engine.UI_TARGET.endswith('/aivan/integrations/order_confirmation.py')
        assert engine.BUILD_KIND == 'offline-order-readback-successor'
        assert engine.PROFILE_SHA256 == engine.build.digest(Path(module.__file__))
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_profile_restores_engine_after_failure():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with pytest.raises(RuntimeError, match='synthetic'):
        with module.order_readback_profile():
            raise RuntimeError('synthetic build failure')
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_facade_is_the_only_selected_runtime_delta(tmp_path):
    module = builder()
    with module.order_readback_profile() as engine:
        source, manifest = selection(tmp_path, engine)
        selected = engine.verify_selection(source, manifest)
        assert selected['source_path'] == 'src/aivan/integrations/order_confirmation.py'
        assert selected['candidate_sha256'] == engine.build.digest(source / engine.UI_SOURCE)


@pytest.mark.parametrize('name', ['src/aivan/app/static/app.js', 'src/aivan/integrations/gltg.py',
                               'alembic/versions/change.py', 'installer/runtime.py', 'installer/requirements.lock'])
def test_profile_rejects_unselected_changes(tmp_path, name):
    module = builder()
    with module.order_readback_profile() as engine:
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
    artifact.write_bytes(b'not the pinned feasibility installer')
    destination = tmp_path / 'payload'
    destination.mkdir()
    with module.order_readback_profile() as engine:
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
        assert module.engine.UI_SOURCE == 'src/aivan/integrations/order_confirmation.py'
        assert module.engine.BUILD_KIND == 'offline-order-readback-successor'
        if failure:
            raise ValueError('synthetic entrypoint failure')
    monkeypatch.setattr(module.engine, 'main', invoke)
    if failure:
        with pytest.raises(ValueError, match='synthetic'):
            module.main()
    else:
        module.main()
    assert len(called) == 1 and 'order readback' in called[0].lower()
    assert {key: getattr(module.engine, key) for key in FIELDS} == original
