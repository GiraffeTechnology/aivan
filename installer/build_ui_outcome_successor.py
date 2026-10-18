#!/usr/bin/env python3
"""Create a one-file UI successor from the verified runtime-repair installer.

This is packaging, not installation or real-service acceptance. Native bytes,
database repairs, migrations, controller and all other components are retained.
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

BASE_SHA256 = "71598a58c89848cd3ea7e592c066bf2d83b4da5c1672d1a956082c06a207b27b"
BASE_REVISION = "c9f9d192c4a0c25c47ad9c42f04da4b69c8a9f10"
BASE_TREE = "144e6de03528f891944b32f4f50e2eb94a6b2c06"
SITE = Path("runtime/lib/python3.12/site-packages")
UI_SOURCE = "src/aivan/app/static/app.js"
UI_TARGET = str(SITE / "aivan/app/static/app.js")
BUILD_KIND = "offline-ui-workflow-outcome-successor"
PROFILE_SHA256 = None


def extract_base(installer: Path, destination: Path) -> dict:
    raw = installer.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError("Selected runtime-repair installer checksum mismatch")
    pieces = raw.split(b"__MYAIVAN_PAYLOAD__\n", 1)
    if len(pieces) != 2:
        raise ValueError("Selected payload marker is missing")
    header, data = pieces
    if hashlib.sha256(data).hexdigest().encode() not in header:
        raise ValueError("Selected payload archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        names = set()
        for member in archive.getmembers():
            name = Path(member.name)
            normalized = str(name)
            if (name.is_absolute() or ".." in name.parts or normalized in names
                    or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe or duplicate selected archive member")
            names.add(normalized)
        archive.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    actual = inventory(destination)
    actual.pop("manifest.json", None)
    if actual != manifest["files"]:
        raise ValueError("Selected payload inventory mismatch")
    identity = manifest.get("deployment_candidate", {})
    if identity.get("revision") != BASE_REVISION or identity.get("upstream_tree") != BASE_TREE:
        raise ValueError("Selected base application identity mismatch")
    return manifest


def fixed_base_tool(source: Path, name: str) -> str:
    try:
        original = build.subprocess.check_output(
            ["git", "-C", str(source), "show", BASE_REVISION + ":" + name],
            stderr=build.subprocess.PIPE,
        )
    except build.subprocess.CalledProcessError:
        raise ValueError("Unselected build input is absent from the fixed base") from None
    digest = build.digest(build.safe_source_file(source, name))
    if digest != hashlib.sha256(original).hexdigest():
        raise ValueError("Unselected build input differs from the fixed base")
    return digest


def verify_selection(source: Path, manifest: dict) -> dict:
    component = manifest["components"]["aivan"]
    baseline = {}
    for field in ("included_source_files", "verified_build_input_files"):
        pinned = component.get(field, {})
        if not isinstance(pinned, dict):
            raise ValueError("Invalid pinned source inventory")
        for name, sha in pinned.items():
            if name in baseline and baseline[name] != sha:
                raise ValueError("Pinned source inventories disagree")
            baseline[name] = sha
    selected = {}
    unchanged_tools = {}
    for name in baseline:
        selected[name] = build.digest(build.safe_source_file(source, name))
        if selected[name] != baseline[name] and name.startswith(("scripts/", "installer/")):
            # Preserve accepted repair-base scripts separately from historical wheel inputs.
            unchanged_tools[name] = fixed_base_tool(source, name)
            baseline[name] = unchanged_tools[name]
    for directory in ("src", "api", "generators", "alembic", "scripts", "installer"):
        root = source / directory
        if root.is_symlink():
            raise ValueError("Source directory links are not permitted")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Source links are not permitted")
            if (path.is_file() and "__pycache__" not in path.parts
                    and not any(part.endswith(".egg-info") for part in path.parts)
                    and str(path.relative_to(source)) not in baseline):
                name = str(path.relative_to(source))
                if directory not in {"installer", "scripts"}:
                    raise ValueError("Runtime additions or removals are not selected")
                # Some retained build tools are outside the wheel inventory.
                # They are accepted only when byte-identical to the fixed base Git blob.
                unchanged_tools[name] = fixed_base_tool(source, name)
    changed = {name for name, sha in selected.items() if sha != baseline[name]}
    if changed != {UI_SOURCE}:
        raise ValueError("Only the selected UI source may differ")
    if manifest["files"].get(UI_TARGET) != baseline[UI_SOURCE]:
        raise ValueError("Installed UI differs from its declared source baseline")
    return {"source_path": UI_SOURCE, "target": UI_TARGET,
            "base_sha256": baseline[UI_SOURCE], "candidate_sha256": selected[UI_SOURCE],
            "unchanged_base_build_inputs": unchanged_tools}


def verify_git_ui(source: Path, revision: str, selected: dict) -> None:
    content = build.subprocess.check_output(["git", "-C", str(source), "show", revision + ":" + UI_SOURCE])
    if hashlib.sha256(content).hexdigest() != selected["candidate_sha256"]:
        raise ValueError("Selected UI differs from its pinned Git blob")


def apply_ui(source: Path, payload: Path, selected: dict) -> None:
    if selected.get("source_path") != UI_SOURCE or selected.get("target") != UI_TARGET:
        raise ValueError("Unexpected UI source or target")
    candidate = build.safe_source_file(source, UI_SOURCE)
    target = build.safe_source_file(payload, UI_TARGET)
    content = candidate.read_bytes()
    if hashlib.sha256(content).hexdigest() != selected["candidate_sha256"]:
        raise ValueError("Selected source changed after verification")
    if build.digest(target) != selected["base_sha256"]:
        raise ValueError("Installed baseline changed after verification")
    target.write_bytes(content)


def main(*, description=None):
    parser = argparse.ArgumentParser(description=description or __doc__)
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
    evidence = build.source_evidence(source, args.revision, args.tree)
    if evidence["modified"]:
        raise ValueError("Selected candidate must be clean and exact")
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"myaivan-{args.release}-linux-x86_64.run"
    companions = [args.output / f"{args.release}-{name}.json" for name in ("manifest", "derived-build")]
    if any(path.exists() or path.is_symlink() for path in (
            destination, destination.with_suffix(".tar.gz"), destination.with_suffix(".run.sha256"), *companions)):
        raise ValueError("Refusing to overwrite an existing artifact")
    with tempfile.TemporaryDirectory(prefix="myaivan-ui-successor-", dir=args.output) as temporary:
        payload = Path(temporary) / "payload"
        payload.mkdir()
        baseline = extract_base(args.base_installer, payload)
        if args.release == baseline["release"]:
            raise ValueError("Select a new release name, not the base release")
        if build.digest(source / "installer/requirements.lock") != baseline["requirements_lock_sha256"]:
            raise ValueError("Frozen runtime dependency lock changed")
        selected = verify_selection(source, baseline)
        verify_git_ui(source, args.revision, selected)
        base_manifest_sha = build.digest(payload / "manifest.json")
        base_provenance = json.loads((payload / "derived-build.json").read_text())
        apply_ui(source, payload, selected)
        provenance = {
            "build_kind": BUILD_KIND, "release": args.release,
            "base_installer_sha256": BASE_SHA256, "base_manifest_sha256": base_manifest_sha,
            "base_derived_build": base_provenance, "selected_application_source": evidence,
            "runtime_delta": [selected], "builder_sha256": build.digest(Path(__file__)),
            "runtime_dependencies": "Byte-identical selected runtime; no downloads, installs or native rebuild",
            "abi_evidence": "Base report retained, not a new host or ABI test",
            "acceptance": "Build integrity only; real-service, MySQL, browser and deployment results are separate",
        }
        if PROFILE_SHA256 is not None:
            provenance["profile_sha256"] = PROFILE_SHA256
        metadata = list((payload / SITE).glob("aivan-*.dist-info"))
        if len(metadata) != 1 or not metadata[0].is_dir() or metadata[0].is_symlink():
            raise ValueError("Expected exactly one selected Aivan distribution")
        write_json(metadata[0] / "DERIVED-BUILD.json", provenance)
        update_record(payload / SITE, metadata[0])
        write_json(payload / "derived-build.json", provenance)
        manifest = copy.deepcopy(baseline)
        component = manifest["components"]["aivan"]
        component["base_source_evidence"] = copy.deepcopy(baseline["components"]["aivan"])
        component["selected_source_candidate"] = evidence
        component["derived_runtime_delta"] = [selected]
        component["modified"] = True
        for field in ("included_source_files", "verified_build_input_files"):
            component[field][UI_SOURCE] = selected["candidate_sha256"]
        manifest.update(release=args.release, build_kind=provenance["build_kind"],
                        base_installer_sha256=BASE_SHA256, deployment_candidate=evidence)
        actual = inventory(payload)
        actual.pop("manifest.json")
        changed = {name for name in baseline["files"].keys() | actual.keys() if baseline["files"].get(name) != actual.get(name)}
        expected = {UI_TARGET, "derived-build.json", str((metadata[0] / "DERIVED-BUILD.json").relative_to(payload)),
                    str((metadata[0] / "RECORD").relative_to(payload))}
        if changed != expected:
            raise ValueError("Payload changed outside UI and exact provenance metadata")
        manifest["files"] = actual
        write_json(payload / "manifest.json", manifest)
        if build.source_evidence(source, args.revision, args.tree) != evidence:
            raise ValueError("Selected source changed during packaging")
        build.write_installer(payload, destination)
        for name in ("manifest", "derived-build"):
            shutil.copy2(payload / f"{name}.json", args.output / f"{args.release}-{name}.json")
        print(json.dumps({"installer": str(destination), "bytes": destination.stat().st_size,
            "sha256": build.digest(destination), "candidate": evidence, "runtime_delta": [selected],
            "changed_payload_files": sorted(changed), "deployment": "NOT_RUN"}, indent=2))


if __name__ == "__main__":
    main()
