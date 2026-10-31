#!/usr/bin/env python3
"""Build the r20 offline installer from verified frozen r18 runtime bytes.

This is a derived payload build, not a wheel rebuild or a new upstream revision.
Only the reviewed r19 application delta is applied. Runtime dependencies remain
byte-identical to the frozen installer; no package registry is accessed.
"""
from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

import build

BASE_SHA256 = "02c3596ab44e25cef6dd8e6202b8a4d9e0bf03fb3467bb360f7c385c6ea6b439"
SNAPSHOT_SHA256 = "58cac9683e7be9e85ffe6444e94b71dcaf1d881502d1035b588eb9315fcd531c"
PATCH_SHA256 = "e62fe10bc2c66f2d9c9fb16f34f4e21a4d4e6140eecbe9ab18d7e007e17ade08"
BASE_METADATA = {
    "aivan-proposed-pr-delta.json": "fe5d4d781cd1d110dc81896b11a02b80811eaac22e805ab1260952c799f3fcec",
    "component-trees/abcdyi-tree.json": "37123c04a30b52c0caa6fcba1bf326cced3129381f9ff4d997f7d865137d7871",
    "component-trees/aivan-tree.json": "63f9024aafd023192f6e33d3869333db91d8bcd2b28573f3d601d17d8f382258",
    "component-trees/database-tree.json": "1b074d84b0cfccc1a7fb6eef88e65149a703cdcc50adf113ce8aac159fc175e3",
    "component-trees/gltg-tree.json": "48872b9d15f085c9840cac908f22083a3f0011a9404a340feac7a22f2c78f707",
    "component-trees/language-tree.json": "8b24b363a72221e59bbc43c493f33134e79d2b1b6302692f75e95e3c684a6e83",
    "dependency-source-reconciliation.json": "f91c4c88170490d9855fe98a077c8d16838e70c9c88f685c622e5cff1541479e",
    "r14-source-reconciliation.json": "3c4b1ae78035c4f79a5051a588441a06894d2bf5224eafb2fc754cc10d10d5ac",
    "source-provenance.json": "7481e6e150d850b5745d1d585c112e8d08b1210118c863b1ecdadd09f7d3f284",
}
SITE = Path("runtime/lib/python3.12/site-packages")
APP_CHANGE = "src/aivan/execution/channel_policy.py"


def write_json(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


def inventory(root, source=False):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if source and ({"__pycache__", ".pytest_cache", ".git"} & set(relative.parts)):
            continue
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError(f"Unsupported source entry: {relative}")
        if path.is_file():
            result[str(relative)] = build.digest(path)
    return result


def extract_frozen(installer, destination):
    if build.digest(installer) != BASE_SHA256:
        raise ValueError("Frozen r18 installer checksum mismatch")
    header, archive = installer.read_bytes().split(b"__MYAIVAN_PAYLOAD__\n", 1)
    archive_sha = hashlib.sha256(archive).hexdigest()
    if archive_sha.encode() not in header:
        raise ValueError("Frozen payload archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        members = stream.getmembers()
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe frozen payload member")
        stream.extractall(destination, members=members, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    actual = inventory(destination)
    actual.pop("manifest.json")
    if actual != manifest["files"]:
        raise ValueError("Frozen payload inventory mismatch")
    return manifest, archive_sha


def verify_source(source, snapshot, patch, work):
    if build.digest(snapshot) != SNAPSHOT_SHA256 or build.digest(patch) != PATCH_SHA256:
        raise ValueError("Frozen source snapshot or reviewed patch checksum mismatch")
    entries = json.loads(snapshot.read_text())
    expected = {f"{item['component']}/{item['path']}": item["sha256"] for item in entries}
    candidate = inventory(source, source=True)
    if candidate.pop("source-snapshot-manifest.json", None) != SNAPSHOT_SHA256:
        raise ValueError("Candidate source must preserve its frozen baseline snapshot")
    for name, value in BASE_METADATA.items():
        if candidate.get(name) != value:
            raise ValueError(f"Frozen source metadata mismatch: {name}")
    additions = {"aivan/installer/build_derived.py", "aivan/installer/DERIVED_BUILD.md"}
    # Reconstruct the reviewed patch on its exact original bytes without trusting
    # a claimed Git SHA for the locally modified source tree.
    comparison = work / "patch-comparison"
    shutil.copytree(source / "aivan", comparison, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    subprocess.run(["git", "apply", "--reverse", str(patch.resolve())], cwd=comparison, check=True, capture_output=True)
    reverse = inventory(comparison, source=True)
    for name, value in expected.items():
        component, local = name.split("/", 1)
        actual = reverse.get(local) if component == "aivan" else candidate.get(name)
        if actual != value:
            raise ValueError(f"Source differs from reviewed frozen base and patch: {name}")
    patch_files = {line.split(" b/", 1)[1] for line in patch.read_text().splitlines() if line.startswith("diff --git ")}
    expected.update(BASE_METADATA)
    allowed = set(expected) | additions | {"aivan/" + name for name in patch_files}
    if set(candidate) - allowed:
        raise ValueError("Unreviewed additional source files: " + ", ".join(sorted(set(candidate) - allowed)))
    changes = {name: {"base_sha256": expected.get(name), "candidate_sha256": value}
               for name, value in candidate.items() if value != expected.get(name)}
    return candidate, changes


def update_record(site, distribution):
    record = distribution / "RECORD"
    rows = list(csv.reader(io.StringIO(record.read_text())))
    names = {row[0] for row in rows}
    names.add(str((distribution / "DERIVED-BUILD.json").relative_to(site)))
    with record.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        for name in sorted(names):
            path = site / name
            if path == record:
                writer.writerow([name, "", ""])
            elif path.is_file():
                content = path.read_bytes()
                digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                writer.writerow([name, "sha256=" + digest, len(content)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-installer", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--reviewed-patch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", default="2026.10.09-candidate-r20")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.release):
        raise ValueError("Invalid release name")
    source = args.source_root.resolve()
    build.require_builder_source(source / "aivan")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="myaivan-derived-", dir=args.output) as temporary:
        work = Path(temporary)
        payload = work / "payload"
        payload.mkdir()
        base, archive_sha = extract_frozen(args.base_installer, payload)
        source_files, source_changes = verify_source(source, args.source_snapshot, args.reviewed_patch, work)
        if build.digest(source / "aivan/installer/requirements.lock") != base["requirements_lock_sha256"]:
            raise ValueError("Dependency lock differs from frozen runtime")
        for component, evidence in base["components"].items():
            for name, expected in evidence["included_source_files"].items():
                if component == "aivan" and name == APP_CHANGE:
                    continue
                if build.digest(source / component / name) != expected:
                    raise ValueError(f"Unchanged provider source mismatch: {component}/{name}")
        target = payload / SITE / APP_CHANGE.removeprefix("src/")
        if build.digest(target) != base["components"]["aivan"]["included_source_files"][APP_CHANGE]:
            raise ValueError("Frozen installed Aivan file does not match frozen source")
        shutil.copy2(source / "aivan" / APP_CHANGE, target)
        provenance = {
            "build_kind": "offline-derived-payload", "release": args.release,
            "base_release": base["release"], "base_installer_sha256": BASE_SHA256,
            "base_archive_sha256": archive_sha, "base_manifest_sha256": build.digest(payload / "manifest.json"),
            "frozen_source_snapshot_sha256": SNAPSHOT_SHA256, "reviewed_patch_sha256": PATCH_SHA256,
            "builder_sha256": build.digest(Path(__file__)), "source_changes": source_changes,
            "source_inventory_sha256": hashlib.sha256(json.dumps(source_files, sort_keys=True).encode()).hexdigest(),
            "runtime_dependencies": "Reused byte-for-byte from verified frozen r18; no network installs or wheel rebuilds",
            "application_delta": "Reviewed r19 openclaw-weixin canonical channel alias",
            "gateway_bridge": "Optional separately supplied tgz; reuse an existing Gateway and configured account",
            "acceptance": "Build/import/integrity/ABI checks only; installed workflow evidence is separate",
        }
        distribution = payload / SITE / "aivan-0.3.0.dist-info"
        # These files refer to the original wheel installer/cache. Record the
        # derived installation explicitly instead of retaining stale wheel claims.
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
        runtime_python = payload / "runtime/bin/python3"
        environment = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "UCX_VFS_ENABLE": "n"}
        subprocess.run([str(runtime_python), "-B", "-I", "-c", "import aivan.api.main,aivan.gpm.server,gltg.api.main,giraffe_db.api.main,giraffe_language_skill.api.main,py3langid,ctranslate2,sentencepiece; print('Offline runtime imports passed')"], cwd=work, env=environment, check=True)
        subprocess.run([str(runtime_python), "-B", "-I", str(payload / "abcdyi_service.py"), "verify-import"], cwd=work, env={**environment, "DATABASE_URL": "sqlite+aiosqlite:///:memory:", "SECRET_KEY": "offline-import-test-fixture-not-a-deployment-credential-0000"}, check=True)
        manifest = copy.deepcopy(base)
        manifest["release"] = args.release
        manifest["build_kind"] = "offline-derived-payload"
        manifest["base_installer_sha256"] = BASE_SHA256
        manifest["frozen_base_wheels"] = manifest.pop("wheels")
        manifest["wheels"] = {}
        component = manifest["components"]["aivan"]
        component["base_source_evidence"] = copy.deepcopy(component)
        component["modified"] = True
        component["revision_semantics"] = "Frozen upstream base commit; local modifications are identified by derived-build.json"
        component.pop("source_manifest_sha256", None)
        for field in ("included_source_files", "verified_build_input_files"):
            component[field][APP_CHANGE] = build.digest(source / "aivan" / APP_CHANGE)
        component["derived_source_changes"] = source_changes
        manifest["abi"] = build.abi_report(payload)
        manifest["files"] = inventory(payload)
        manifest["files"].pop("manifest.json")
        write_json(payload / "manifest.json", manifest)
        destination = args.output / f"myaivan-{args.release}-linux-x86_64.run"
        build.write_installer(payload, destination)
        for name in ("manifest", "sbom", "derived-build"):
            shutil.copy2(payload / f"{name}.json", args.output / f"{args.release}-{name}.json")
        write_json(args.output / f"{args.release}-source-inventory.json", source_files)
        write_json(args.output / f"{args.release}-source-delta.json", source_changes)
        print(json.dumps({"installer": str(destination), "sha256": build.digest(destination), "size_bytes": destination.stat().st_size, "source_changes": len(source_changes), "abi": manifest["abi"]}, indent=2))


if __name__ == "__main__":
    main()
