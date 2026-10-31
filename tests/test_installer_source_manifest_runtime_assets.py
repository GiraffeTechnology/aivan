"""Manifest-pinned builds bind all runtime scripts and installer helpers."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


def builder():
    source = Path(__file__).resolve().parents[1] / "installer/build.py"
    spec = importlib.util.spec_from_file_location("manifest_asset_builder", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned_source(tmp_path, directory):
    source = tmp_path / "source"
    source.mkdir()
    path = source / directory / "runtime_asset.py"
    path.parent.mkdir()
    path.write_text("SYNTHETIC_VALUE = 1\n")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    tree = subprocess.check_output(["git", "-C", str(source), "write-tree"], text=True).strip()
    record = subprocess.check_output(["git", "-C", str(source), "ls-files", "-s"], text=True)
    mode, sha, _ = record.split("\t")[0].split()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([{"path": str(path.relative_to(source)), "type": "blob",
                                     "mode": mode, "sha": sha}]))
    return source, path, tree, manifest


@pytest.mark.parametrize("directory", ["src", "api", "generators", "alembic", "scripts", "installer"])
def test_manifest_verifies_included_runtime_asset_bytes(tmp_path, directory):
    source, path, tree, manifest = pinned_source(tmp_path, directory)
    build = builder()
    evidence = build.source_evidence(source, "a" * 40, tree, manifest)
    assert str(path.relative_to(source)) in evidence["verified_build_input_files"]
    assert (str(path.relative_to(source)) in evidence["included_source_files"]) == (
        directory not in {"scripts", "installer"}
    )
    path.write_text("SYNTHETIC_VALUE = 2\n")
    with pytest.raises(ValueError, match="blob mismatch"):
        build.source_evidence(source, "a" * 40, tree, manifest)


@pytest.mark.parametrize("directory", ["scripts", "installer"])
def test_manifest_rejects_unpinned_runtime_helpers(tmp_path, directory):
    source, path, tree, manifest = pinned_source(tmp_path, directory)
    (path.parent / "unexpected.py").write_text("SYNTHETIC_VALUE = 3\n")
    with pytest.raises(ValueError, match="Unpinned provider runtime input"):
        builder().source_evidence(source, "a" * 40, tree, manifest)


def test_builder_helpers_cannot_come_from_a_different_checkout(tmp_path, monkeypatch):
    build = builder()
    selected = tmp_path / "selected"
    selected.mkdir()
    monkeypatch.setattr(build, "HERE", selected / "installer")
    build.require_builder_source(selected)
    with pytest.raises(ValueError, match="selected pinned Aivan source"):
        build.require_builder_source(tmp_path / "different-checkout")
