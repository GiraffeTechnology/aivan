"""Scoped successor-builder tests; not a full payload build or provider acceptance."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "installer"))
import build_successor as successor


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def selected(tmp_path):
    source = tmp_path / "source"
    runtime = sorted(successor.RUNTIME_DELTA | {"src/aivan/unchanged.py"})
    original = {}
    for name in runtime:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original synthetic source\n")
        original[name] = digest(path)
        if name in successor.RUNTIME_DELTA:
            path.write_text("reviewed synthetic replacement\n")
    lock = source / "installer/requirements.lock"
    lock.parent.mkdir()
    lock.write_text("synthetic exact lock\n")
    manifest = {"components": {"aivan": {"included_source_files": original}},
                "requirements_lock_sha256": digest(lock)}
    return source, manifest


def test_exact_three_runtime_files_are_selected(selected):
    source, manifest = selected
    changes = successor.verify_runtime_selection(source, manifest)
    assert set(changes) == successor.RUNTIME_DELTA
    for name, change in changes.items():
        assert change["candidate_sha256"] == digest(source / name)
        assert change["installed_path"].endswith(name.removeprefix("src/"))


@pytest.mark.parametrize("kind", ["addition", "removal", "unreviewed_change", "lock", "missing_delta"])
def test_unreviewed_or_incomplete_selection_is_rejected(selected, kind):
    source, manifest = selected
    untouched = source / "src/aivan/unchanged.py"
    if kind == "addition":
        (source / "src/aivan/extra.py").write_text("new runtime\n")
    elif kind == "removal":
        untouched.unlink()
    elif kind == "unreviewed_change":
        untouched.write_text("unexpected change\n")
    elif kind == "lock":
        (source / "installer/requirements.lock").write_text("different dependency\n")
    else:
        (source / sorted(successor.RUNTIME_DELTA)[0]).write_text("original synthetic source\n")
    with pytest.raises(ValueError):
        successor.verify_runtime_selection(source, manifest)


def test_runtime_copy_preserves_dependencies_and_updates_all_three_files(selected, tmp_path):
    source, manifest = selected
    payload = tmp_path / "payload"
    changes = successor.verify_runtime_selection(source, manifest)
    for name in manifest["components"]["aivan"]["included_source_files"]:
        path = payload / successor.SITE / name.removeprefix("src/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original synthetic source\n")
    dependency = payload / successor.SITE / "dependency.py"
    dependency.write_text("frozen dependency bytes\n")
    expected_dependency = digest(dependency)
    successor.apply_runtime_delta(source, payload, manifest, changes)
    assert digest(dependency) == expected_dependency
    for name in changes:
        assert (payload / successor.SITE / name.removeprefix("src/")).read_bytes() == (source / name).read_bytes()


def test_baseline_mismatch_fails_before_any_runtime_copy(selected, tmp_path):
    source, manifest = selected
    payload = tmp_path / "payload"
    changes = successor.verify_runtime_selection(source, manifest)
    before = {}
    for index, name in enumerate(changes):
        path = payload / successor.SITE / name.removeprefix("src/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("wrong base\n" if index == 1 else "original synthetic source\n")
        before[path] = path.read_bytes()
    with pytest.raises(ValueError):
        successor.apply_runtime_delta(source, payload, manifest, changes)
    assert all(path.read_bytes() == original for path, original in before.items())


def test_record_rehashes_runtime_and_derived_provenance(tmp_path):
    site = tmp_path / "site"
    distribution = site / "aivan-0.3.0.dist-info"
    distribution.mkdir(parents=True)
    runtime = site / "aivan/app.js"
    runtime.parent.mkdir()
    runtime.write_text("new selected source\n")
    record = distribution / "RECORD"
    record.write_text("aivan/app.js,stale,1\naivan-0.3.0.dist-info/RECORD,,\n")
    provenance = distribution / "DERIVED-BUILD.json"
    provenance.write_text(json.dumps({"selected_source": "synthetic"}))
    successor.update_record(site, distribution)
    rows = {row[0]: row[1:] for row in csv.reader(io.StringIO(record.read_text()))}
    for path in (runtime, provenance):
        expected = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b"=").decode()
        assert rows[str(path.relative_to(site))] == ["sha256=" + expected, str(path.stat().st_size)]
    assert rows[str(record.relative_to(site))] == ["", ""]
