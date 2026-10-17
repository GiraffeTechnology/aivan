"""Synthetic build-integrity regressions; not target deployment acceptance."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest


def builder():
    directory = Path(__file__).resolve().parents[1] / "installer"
    path = directory / "build_runtime_repair.py"
    assert path.is_file(), "the bounded runtime repair builder is not implemented"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("runtime_repair_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def component(tmp_path, module, name):
    source = tmp_path / name
    path = next(iter(module.RUNTIME_DELTAS[name]))
    package = "aivan" if name == "aivan" else "giraffe_db"
    baseline = {}
    for relative in (path, f"src/{package}/unchanged.py"):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original synthetic source\n")
        baseline[relative] = module.build.digest(target)
    (source / path).write_text("reviewed synthetic replacement\n")
    return source, {"included_source_files": baseline}


def payload_inventory(module, name, original):
    path = next(iter(module.RUNTIME_DELTAS[name]))
    digest = original["included_source_files"][path]
    result = {str(module.SITE / path.removeprefix("src/")): digest}
    if name == "database":
        result["provider-assets/giraffe-db/" + path] = digest
    return result


@pytest.mark.parametrize("name", ["aivan", "database"])
def test_exact_runtime_delta_and_database_mirror_are_selected(tmp_path, name):
    module = builder()
    source, original = component(tmp_path, module, name)
    selected = module.verify_component(source, name, original, payload_files=payload_inventory(module, name, original))
    assert len(selected) == 1
    replacement = selected[0]
    assert replacement["source_path"] in module.RUNTIME_DELTAS[name]
    assert len(replacement["targets"]) == (2 if name == "database" else 1)
    assert replacement["candidate_sha256"] == module.build.digest(source / replacement["source_path"])
    assert all(".." not in Path(target).parts for target in replacement["targets"])


@pytest.mark.parametrize("kind", ["addition", "removal", "other_change", "missing_fix", "source_link"])
def test_unselected_or_incomplete_runtime_changes_are_rejected(tmp_path, kind):
    module = builder()
    source, original = component(tmp_path, module, "aivan")
    changed = source / next(iter(module.RUNTIME_DELTAS["aivan"]))
    untouched = source / "src/aivan/unchanged.py"
    if kind == "addition":
        (source / "src/aivan/extra.py").write_text("unselected source\n")
    elif kind == "removal":
        untouched.unlink()
    elif kind == "other_change":
        untouched.write_text("unexpected change\n")
    elif kind == "missing_fix":
        changed.write_text("original synthetic source\n")
    else:
        changed.unlink()
        changed.symlink_to(untouched)
    with pytest.raises(ValueError):
        module.verify_component(source, "aivan", original, payload_files=payload_inventory(module, "aivan", original))


def prepare_copy(tmp_path, module):
    payload = tmp_path / "payload"
    rows = []
    for name in ("aivan", "database"):
        source, original = component(tmp_path, module, name)
        selected = module.verify_component(source, name, original, payload_files=payload_inventory(module, name, original))
        for row in selected:
            for target in row["targets"]:
                destination = payload / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("original synthetic source\n")
        rows.extend(selected)
    return payload, rows


def test_copy_updates_both_database_locations_without_touching_dependencies(tmp_path):
    module = builder()
    payload, rows = prepare_copy(tmp_path, module)
    dependency = payload / "runtime/dependency.bin"
    dependency.write_bytes(b"frozen dependency bytes")
    for row in rows:
        for target in row["targets"]:
            (payload / target).chmod(0o640)
    module.apply_replacements(payload, rows)
    for row in rows:
        for target in row["targets"]:
            assert module.build.digest(payload / target) == row["candidate_sha256"]
            assert (payload / target).stat().st_mode & 0o777 == 0o640
    assert dependency.read_bytes() == b"frozen dependency bytes"


def test_database_without_declared_source_mirror_updates_only_installed_module(tmp_path):
    module = builder()
    source, original = component(tmp_path, module, "database")
    path = next(iter(module.RUNTIME_DELTAS["database"]))
    installed = str(module.SITE / path.removeprefix("src/"))
    files = {installed: original["included_source_files"][path]}
    selected = module.verify_component(source, "database", original, payload_files=files)
    assert selected[0]["targets"] == [installed]


@pytest.mark.parametrize("kind", ["missing_installed", "mismatched_declared_mirror"])
def test_declared_payload_locations_must_match_original_source(tmp_path, kind):
    module = builder()
    source, original = component(tmp_path, module, "database")
    path = next(iter(module.RUNTIME_DELTAS["database"]))
    files = {str(module.SITE / path.removeprefix("src/")): original["included_source_files"][path]}
    if kind == "missing_installed":
        files.clear()
    else:
        files["provider-assets/giraffe-db/" + path] = "different baseline"
    with pytest.raises(ValueError):
        module.verify_component(source, "database", original, payload_files=files)


@pytest.mark.parametrize("kind", ["target_drift", "source_drift", "target_link"])
def test_all_inputs_are_checked_before_any_copy(tmp_path, kind):
    module = builder()
    payload, rows = prepare_copy(tmp_path, module)
    first = payload / rows[0]["targets"][0]
    before = first.read_bytes()
    last = payload / rows[-1]["targets"][-1]
    if kind == "target_drift":
        last.write_text("unexpected baseline\n")
    elif kind == "source_drift":
        (rows[-1]["_source"] / rows[-1]["source_path"]).write_text("changed after verification\n")
    else:
        last.unlink()
        last.symlink_to(first)
    with pytest.raises(ValueError):
        module.apply_replacements(payload, rows)
    assert first.read_bytes() == before


@pytest.mark.parametrize("kind", ["traversal", "duplicate", "symlink", "inventory", "header"])
def test_invalid_frozen_archive_is_rejected(tmp_path, monkeypatch, kind):
    module = builder()
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as archive:
        names = ["../escape"] if kind == "traversal" else ["example.py", "./example.py"] if kind == "duplicate" else ["example.py"]
        for name in names:
            item = tarfile.TarInfo(name)
            content = b"original source\n"
            if kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "outside"
            else:
                item.size = len(content)
            archive.addfile(item, io.BytesIO(content) if item.isfile() else None)
        item = tarfile.TarInfo("manifest.json")
        raw = json.dumps({"files": {"example.py": "wrong"}}).encode()
        item.size = len(raw)
        archive.addfile(item, io.BytesIO(raw))
    data = memory.getvalue()
    import hashlib
    header_hash = "0" * 64 if kind == "header" else hashlib.sha256(data).hexdigest()
    package = tmp_path / "synthetic.run"
    package.write_bytes(("#!/bin/sh\n" + header_hash + "\n__MYAIVAN_PAYLOAD__\n").encode() + data)
    monkeypatch.setattr(module, "BASE_SHA256", module.build.digest(package))
    destination = tmp_path / "extracted"
    destination.mkdir()
    with pytest.raises(ValueError):
        module.extract_base(package, destination)


def test_wrong_frozen_installer_digest_fails_before_extraction(tmp_path):
    module = builder()
    package = tmp_path / "wrong.run"
    package.write_bytes(b"not the frozen package")
    destination = tmp_path / "extracted"
    destination.mkdir()
    with pytest.raises(ValueError):
        module.extract_base(package, destination)
    assert list(destination.iterdir()) == []
