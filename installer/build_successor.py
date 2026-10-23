#!/usr/bin/env python3
"""Build an offline successor from verified r20 bytes and exact Aivan source.

This entry point preserves the original r18/r20 builders and their provenance.
It replaces only the three reviewed Aivan runtime files; no dependency is built,
installed or downloaded. Build/import checks are not deployed workflow acceptance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

import build
from build_derived import inventory, update_record, write_json

BASE_SHA256 = "0fc7016566ea6a5234e313dbb69358b298acb28b13bbd2ab79e71d4c7ebfd330"
SITE = Path("runtime/lib/python3.12/site-packages")
RUNTIME_DELTA = frozenset({
    "src/aivan/api/workbench_routes.py",
    "src/aivan/app/static/app.js",
    "src/aivan/integrations/giraffe_db.py",
})


def verify_runtime_selection(source: Path, manifest: dict) -> dict:
    """Reject an unreviewed runtime addition, removal, change or lock drift."""
    baseline = manifest["components"]["aivan"]["included_source_files"]
    selected = {str(path.relative_to(source)): build.digest(path)
                for path in (source / "src").rglob("*")
                if path.is_file() and "__pycache__" not in path.parts}
    expected = {name: sha for name, sha in baseline.items() if name.startswith("src/")}
    if selected.keys() != expected.keys():
        raise ValueError("Aivan runtime file inventory differs from the reviewed source selection")
    for name in selected:
        build.safe_source_file(source, name)
    changed = {name for name in selected if selected[name] != expected[name]}
    if changed != RUNTIME_DELTA:
        raise ValueError("Aivan runtime delta is not the exact reviewed three-file selection")
    if build.digest(source / "installer/requirements.lock") != manifest["requirements_lock_sha256"]:
        raise ValueError("Runtime dependency lock changed; frozen dependency reuse is not valid")
    return {name: {"base_sha256": expected[name], "candidate_sha256": selected[name],
                   "installed_path": str(SITE / name.removeprefix("src/"))}
            for name in sorted(changed)}


def extract_base(installer: Path, destination: Path) -> tuple[dict, str]:
    if build.digest(installer) != BASE_SHA256:
        raise ValueError("Frozen r20 installer checksum mismatch")
    header, archive = installer.read_bytes().split(b"__MYAIVAN_PAYLOAD__\n", 1)
    archive_sha = hashlib.sha256(archive).hexdigest()
    if archive_sha.encode() not in header:
        raise ValueError("Frozen r20 archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        names = set()
        for member in stream.getmembers():
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or member.name in names \
                    or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe or duplicate frozen payload member")
            names.add(member.name)
        stream.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    actual = inventory(destination)
    actual.pop("manifest.json")
    if actual != manifest["files"]:
        raise ValueError("Frozen r20 payload inventory mismatch")
    return manifest, archive_sha


def apply_runtime_delta(source: Path, payload: Path, manifest: dict, changes: dict) -> None:
    """Confirm installed baseline bytes before copying any replacement."""
    for name in changes:
        target = payload / SITE / name.removeprefix("src/")
        if build.digest(target) != changes[name]["base_sha256"]:
            raise ValueError("Frozen installed Aivan runtime differs from its source manifest")
    for name in changes:
        shutil.copy2(build.safe_source_file(source, name), payload / SITE / name.removeprefix("src/"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-installer", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.release):
        raise ValueError("Invalid release name")
    source = args.source.resolve()
    build.require_builder_source(source)
    evidence = build.source_evidence(source, args.revision, args.tree)
    if evidence["modified"]:
        raise ValueError("Candidate source must be clean and match the exact commit/tree")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="myaivan-successor-", dir=args.output) as temporary:
        work = Path(temporary)
        payload = work / "payload"
        payload.mkdir()
        base, archive_sha = extract_base(args.base_installer, payload)
        base_manifest_sha = build.digest(payload / "manifest.json")
        changes = verify_runtime_selection(source, base)
        names = build.run("git", "-C", source, "ls-files", "-z", capture_output=True).stdout.decode().split("\0")
        source_files = {name: build.digest(build.safe_source_file(source, name)) for name in names if name}
        apply_runtime_delta(source, payload, base, changes)
        provenance = {
            "build_kind": "offline-r20-successor-three-file-delta", "release": args.release,
            "base_release": base["release"], "base_installer_sha256": BASE_SHA256,
            "base_archive_sha256": archive_sha, "base_manifest_sha256": base_manifest_sha,
            "selected_aivan_source": evidence, "runtime_delta": changes,
            "builder_sha256": build.digest(Path(__file__)),
            "source_inventory_sha256": hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest(),
            "runtime_dependencies": "Byte-identical verified r20 runtime; no dependency downloads, installs or wheel rebuilds",
            "acceptance": "Build/import/ABI only; real providers, browser workflow and deployment require separate evidence",
        }
        distribution = payload / SITE / "aivan-0.3.0.dist-info"
        for name in ("direct_url.json", "uv_cache.json"):
            (distribution / name).unlink(missing_ok=True)
        write_json(distribution / "DERIVED-BUILD.json", provenance)
        update_record(payload / SITE, distribution)
        write_json(payload / "derived-build.json", provenance)
        sbom = json.loads((payload / "sbom.json").read_text())
        for entry in sbom:
            if entry["name"].lower() == "aivan":
                entry["modified_from_frozen_distribution"] = True
                entry["provenance_file"] = "derived-build.json"
        write_json(payload / "sbom.json", sbom)
        environment = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1",
                       "TRANSFORMERS_OFFLINE": "1", "UCX_VFS_ENABLE": "n"}
        build.run(payload / "runtime/bin/python3", "-B", "-I", "-c",
                  "import aivan.api.main,aivan.gpm.server,gltg.api.main,giraffe_db.api.main,giraffe_language_skill.api.main; print('Successor offline imports passed')",
                  cwd=work, env=environment)
        manifest = copy.deepcopy(base)
        manifest.update(release=args.release, build_kind=provenance["build_kind"],
                        base_installer_sha256=BASE_SHA256, deployment_candidate=evidence)
        # Retain original wheel/source identities rather than claiming a rebuilt wheel.
        component = manifest["components"]["aivan"]
        component["base_source_evidence"] = copy.deepcopy(base["components"]["aivan"])
        component["selected_source_candidate"] = evidence
        component["modified"] = True
        component["revision_semantics"] = "Base wheel provenance retained; exact successor runtime source is selected_source_candidate"
        component["derived_runtime_delta"] = changes
        for name, change in changes.items():
            for field in ("included_source_files", "verified_build_input_files"):
                component[field][name] = change["candidate_sha256"]
        manifest["abi"] = build.abi_report(payload)
        manifest["files"] = inventory(payload)
        manifest["files"].pop("manifest.json")
        write_json(payload / "manifest.json", manifest)
        destination = args.output / f"myaivan-{args.release}-linux-x86_64.run"
        if destination.exists():
            raise ValueError("Refusing to overwrite an existing release installer")
        build.write_installer(payload, destination)
        for name in ("manifest", "sbom", "derived-build"):
            shutil.copy2(payload / f"{name}.json", args.output / f"{args.release}-{name}.json")
        write_json(args.output / f"{args.release}-source-inventory.json", source_files)
        write_json(args.output / f"{args.release}-source-delta.json", changes)
        print(json.dumps({"installer": str(destination), "bytes": destination.stat().st_size,
                          "sha256": build.digest(destination), "revision": args.revision,
                          "tree": args.tree, "runtime_changes": sorted(changes)}, indent=2))


if __name__ == "__main__":
    main()
