"""The quote profile must reuse the one-source integrity engine without widening it."""
import importlib.util
from pathlib import Path
import sys

import pytest

from tests.test_myaivan_ui_outcome_builder import selection


def builder():
    directory = Path(__file__).resolve().parents[1] / 'installer'
    path = directory / 'build_quote_validity_successor.py'
    assert path.is_file(), 'the bounded quote successor profile is not implemented'
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location('quote_successor_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIELDS = ('BASE_SHA256', 'BASE_REVISION', 'BASE_TREE', 'UI_SOURCE', 'UI_TARGET', 'BUILD_KIND', 'PROFILE_SHA256')


def test_exact_profile_and_restoration():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with module.quote_profile() as engine:
        assert engine.BASE_SHA256 == 'd27b7126bac1049e51d36c651992e1ed64e155e0d5f4ce9e879a8d4103c680d9'
        assert engine.BASE_REVISION == '1932885324a895030b6e5b284e36be577edc2291'
        assert engine.BASE_TREE == '92fc20ae2aa1942d432bde05a2329420723575a7'
        assert engine.UI_SOURCE == 'src/aivan/agents/buyer_option_agent.py'
        assert engine.UI_TARGET.endswith('/aivan/agents/buyer_option_agent.py')
        assert engine.BUILD_KIND == 'offline-quote-price-validity-successor'
        assert engine.PROFILE_SHA256 == engine.build.digest(Path(module.__file__))
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_profile_restores_ui_builder_after_failure():
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    with pytest.raises(RuntimeError, match='synthetic'):
        with module.quote_profile():
            raise RuntimeError('synthetic build failure')
    assert {key: getattr(module.engine, key) for key in FIELDS} == original


def test_quote_file_is_the_only_selected_runtime_delta(tmp_path):
    module = builder()
    with module.quote_profile() as engine:
        source, manifest = selection(tmp_path, engine)
        selected = engine.verify_selection(source, manifest)
        assert selected['source_path'] == 'src/aivan/agents/buyer_option_agent.py'
        assert selected['candidate_sha256'] == engine.build.digest(source / engine.UI_SOURCE)


@pytest.mark.parametrize('name', ['src/aivan/app/static/app.js', 'api/server.py',
    'alembic/versions/change.py', 'installer/runtime.py', 'installer/requirements.lock'])
def test_quote_profile_cannot_smuggle_other_changes(tmp_path, name):
    module = builder()
    with module.quote_profile() as engine:
        source, manifest = selection(tmp_path, engine)
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original pinned bytes')
        manifest['components']['aivan']['verified_build_input_files'] = {name: engine.build.digest(path)}
        path.write_bytes(b'unselected change')
        with pytest.raises(ValueError):
            engine.verify_selection(source, manifest)


def test_wrong_ui_base_is_rejected_before_extraction(tmp_path):
    module = builder()
    artifact = tmp_path / 'wrong-base.run'
    artifact.write_bytes(b'not the pinned 193 installer')
    destination = tmp_path / 'payload'
    destination.mkdir()
    with module.quote_profile() as engine:
        with pytest.raises(ValueError, match='checksum'):
            engine.extract_base(artifact, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize('failure', [False, True])
def test_entrypoint_uses_profile_and_always_restores_defaults(monkeypatch, failure):
    module = builder()
    original = {key: getattr(module.engine, key) for key in FIELDS}
    called = []
    def invoke(*, description):
        called.append(description)
        assert module.engine.UI_SOURCE == 'src/aivan/agents/buyer_option_agent.py'
        assert module.engine.BUILD_KIND == 'offline-quote-price-validity-successor'
        if failure:
            raise ValueError('synthetic entrypoint failure')
    monkeypatch.setattr(module.engine, 'main', invoke)
    if failure:
        with pytest.raises(ValueError, match='synthetic'):
            module.main()
    else:
        module.main()
    assert len(called) == 1 and 'quote' in called[0].lower()
    assert {key: getattr(module.engine, key) for key in FIELDS} == original
