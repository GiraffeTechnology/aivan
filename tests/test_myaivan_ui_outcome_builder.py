"""Synthetic integrity checks for the selected one-file UI successor."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest


def builder():
    directory = Path(__file__).resolve().parents[1] / "installer"
    path = directory / "build_ui_outcome_successor.py"
    assert path.is_file(), "the bounded UI successor builder is not implemented"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location("ui_successor_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selection(tmp_path, module):
    source = tmp_path / "source"
    original = {}
    for name in [module.UI_SOURCE, "src/aivan/unchanged.py"]:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original bytes\n")
        original[name] = module.build.digest(path)
    (source / module.UI_SOURCE).write_text("reviewed UI bytes\n")
    manifest = {"components": {"aivan": {"included_source_files": original}},
                "files": {module.UI_TARGET: original[module.UI_SOURCE]}}
    return source, manifest


def test_selects_only_reviewed_ui_file(tmp_path):
    module = builder()
    source, manifest = selection(tmp_path, module)
    selected = module.verify_selection(source, manifest)
    assert selected["source_path"] == module.UI_SOURCE
    assert selected["target"] == module.UI_TARGET
    assert selected["candidate_sha256"] == module.build.digest(source / module.UI_SOURCE)


@pytest.mark.parametrize("kind", ["extra", "removed", "other_change", "no_change", "source_link", "installed_mismatch"])
def test_rejects_unselected_runtime_inputs(tmp_path, kind):
    module = builder()
    source, manifest = selection(tmp_path, module)
    target = source / module.UI_SOURCE
    other = source / "src/aivan/unchanged.py"
    if kind == "extra":
        (source / "src/aivan/extra.py").write_text("not selected\n")
    elif kind == "removed":
        other.unlink()
    elif kind == "other_change":
        other.write_text("not selected\n")
    elif kind == "no_change":
        target.write_text("original bytes\n")
    elif kind == "source_link":
        target.unlink()
        target.symlink_to(other)
    else:
        manifest["files"][module.UI_TARGET] = "wrong"
    with pytest.raises(ValueError):
        module.verify_selection(source, manifest)


@pytest.mark.parametrize("kind", ["valid", "source_drift", "target_drift", "target_link"])
def test_copy_preserves_mode_and_rejects_drift(tmp_path, kind):
    module = builder()
    source, manifest = selection(tmp_path, module)
    selected = module.verify_selection(source, manifest)
    payload = tmp_path / "payload"
    target = payload / module.UI_TARGET
    target.parent.mkdir(parents=True)
    target.write_text("original bytes\n")
    target.chmod(0o640)
    untouched = payload / "native.bin"
    untouched.write_bytes(b"unchanged native runtime")
    if kind == "source_drift":
        (source / module.UI_SOURCE).write_text("changed after selection\n")
    elif kind == "target_drift":
        target.write_text("unexpected baseline\n")
    elif kind == "target_link":
        target.unlink()
        target.symlink_to(untouched)
    if kind == "valid":
        module.apply_ui(source, payload, selected)
        assert target.read_text() == "reviewed UI bytes\n"
        assert target.stat().st_mode & 0o777 == 0o640
    else:
        with pytest.raises(ValueError):
            module.apply_ui(source, payload, selected)
    assert untouched.read_bytes() == b"unchanged native runtime"


@pytest.mark.parametrize("kind", ["traversal", "duplicate", "link", "inventory", "header"])
def test_rejects_invalid_base_archive(tmp_path, monkeypatch, kind):
    module = builder()
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz") as archive:
        names = ["../escape"] if kind == "traversal" else ["app.js", "./app.js"] if kind == "duplicate" else ["app.js"]
        for name in names:
            item = tarfile.TarInfo(name)
            raw = b"original bytes"
            if kind == "link":
                item.type = tarfile.SYMTYPE
                item.linkname = "outside"
            else:
                item.size = len(raw)
            archive.addfile(item, io.BytesIO(raw) if item.isfile() else None)
        manifest = json.dumps({"files": {"app.js": "wrong"}}).encode()
        item = tarfile.TarInfo("manifest.json")
        item.size = len(manifest)
        archive.addfile(item, io.BytesIO(manifest))
    import hashlib
    data = content.getvalue()
    digest = "0" * 64 if kind == "header" else hashlib.sha256(data).hexdigest()
    path = tmp_path / "synthetic.run"
    path.write_bytes(("#!/bin/sh\n" + digest + "\n__MYAIVAN_PAYLOAD__\n").encode() + data)
    monkeypatch.setattr(module, "BASE_SHA256", module.build.digest(path))
    destination = tmp_path / "extract"
    destination.mkdir()
    with pytest.raises(ValueError):
        module.extract_base(path, destination)


def test_wrong_base_digest_rejected_before_extraction(tmp_path):
    module = builder()
    path = tmp_path / "wrong.run"
    path.write_bytes(b"not selected base")
    destination = tmp_path / "extract"
    destination.mkdir()
    with pytest.raises(ValueError):
        module.extract_base(path, destination)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("identity", ["valid", "revision", "tree"])
def test_base_inventory_and_application_identity_are_both_verified(tmp_path, monkeypatch, identity):
    module = builder()
    import hashlib
    raw = b"original UI"
    manifest = {"files": {"app.js": hashlib.sha256(raw).hexdigest()},
                "deployment_candidate": {"revision": module.BASE_REVISION, "upstream_tree": module.BASE_TREE}}
    if identity != "valid":
        key = "revision" if identity == "revision" else "upstream_tree"
        manifest["deployment_candidate"][key] = "0" * 40
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as archive:
        for name, data in [("app.js", raw), ("manifest.json", json.dumps(manifest).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    data = memory.getvalue()
    path = tmp_path / "synthetic.run"
    path.write_bytes(("#!/bin/sh\n" + hashlib.sha256(data).hexdigest() + "\n__MYAIVAN_PAYLOAD__\n").encode() + data)
    monkeypatch.setattr(module, "BASE_SHA256", module.build.digest(path))
    destination = tmp_path / "extract"
    destination.mkdir()
    if identity == "valid":
        assert module.extract_base(path, destination) == manifest
    else:
        with pytest.raises(ValueError, match="identity mismatch"):
            module.extract_base(path, destination)


@pytest.mark.parametrize("name", ["api/server.py", "alembic/versions/change.py", "generators/model.py",
                                 "scripts/run_aivan_migrations.py", "installer/runtime.py", "pyproject.toml"])
def test_rejects_changes_to_every_pinned_build_input(tmp_path, name):
    module = builder()
    source, manifest = selection(tmp_path, module)
    path = source / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("pinned build input\n")
    manifest["components"]["aivan"]["verified_build_input_files"] = {name: module.build.digest(path)}
    path.write_text("unselected change\n")
    with pytest.raises(ValueError):
        module.verify_selection(source, manifest)


def test_base_hash_and_extraction_consume_one_identical_read(tmp_path, monkeypatch):
    module = builder()
    import hashlib
    raw = b"original UI"
    manifest = {"files": {"app.js": hashlib.sha256(raw).hexdigest()},
                "deployment_candidate": {"revision": module.BASE_REVISION, "upstream_tree": module.BASE_TREE}}
    memory = io.BytesIO()
    with tarfile.open(fileobj=memory, mode="w:gz") as archive:
        for name, content in [("app.js", raw), ("manifest.json", json.dumps(manifest).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    data = memory.getvalue()
    path = tmp_path / "synthetic.run"
    path.write_bytes(("#!/bin/sh\n" + hashlib.sha256(data).hexdigest() + "\n__MYAIVAN_PAYLOAD__\n").encode() + data)
    monkeypatch.setattr(module, "BASE_SHA256", module.build.digest(path))
    original_read = Path.read_bytes
    reads = []
    def replace_after_read(target):
        content = original_read(target)
        if target == path:
            reads.append(target)
            target.write_bytes(b"untrusted replacement after initial read")
        return content
    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    destination = tmp_path / "extract"
    destination.mkdir()
    assert module.extract_base(path, destination) == manifest
    assert reads == [path]


@pytest.mark.parametrize("companion", ["manifest", "derived-build"])
def test_companion_evidence_must_not_be_overwritten(tmp_path, monkeypatch, companion):
    module = builder()
    output = tmp_path / "output"
    output.mkdir()
    saved = output / f"successor-{companion}.json"
    saved.write_text("existing evidence")
    monkeypatch.setattr(module.build, "source_evidence", lambda *args: {"modified": False})
    def forbidden_extract(*args):
        raise AssertionError("Existing evidence must be rejected before extraction")
    monkeypatch.setattr(module, "extract_base", forbidden_extract)
    monkeypatch.setattr(sys, "argv", ["builder", "--base-installer", str(tmp_path / "base.run"),
        "--source", str(tmp_path), "--revision", "a" * 40, "--tree", "b" * 40,
        "--output", str(output), "--release", "successor"])
    with pytest.raises(ValueError):
        module.main()
    assert saved.read_text() == "existing evidence"


def test_existing_base_release_name_is_rejected(tmp_path, monkeypatch):
    module = builder()
    monkeypatch.setattr(module.build, "source_evidence", lambda *args: {"modified": False})
    monkeypatch.setattr(module, "extract_base", lambda *args: {"release": "same-release"})
    monkeypatch.setattr(sys, "argv", ["builder", "--base-installer", str(tmp_path / "base.run"),
        "--source", str(tmp_path), "--revision", "a" * 40, "--tree", "b" * 40,
        "--output", str(tmp_path / "output"), "--release", "same-release"])
    with pytest.raises(ValueError, match="release"):
        module.main()


@pytest.mark.parametrize("blob", [b"reviewed UI bytes\n", b"different committed UI bytes\n"])
def test_selected_ui_bytes_must_equal_the_pinned_git_blob(tmp_path, monkeypatch, blob):
    module = builder()
    source, manifest = selection(tmp_path, module)
    selected = module.verify_selection(source, manifest)
    calls = []
    def git_read(argv):
        calls.append(argv)
        return blob
    monkeypatch.setattr(module.build.subprocess, "check_output", git_read)
    if blob == b"reviewed UI bytes\n":
        module.verify_git_ui(source, "a" * 40, selected)
    else:
        with pytest.raises(ValueError):
            module.verify_git_ui(source, "a" * 40, selected)
    assert calls == [["git", "-C", str(source), "show", "a" * 40 + ":" + module.UI_SOURCE]]
