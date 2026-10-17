#!/usr/bin/env python3
"""Repack the verified integrated installer with two selected Python repairs.

Dependencies, binaries, migrations, controller and unrelated components remain
byte-identical. This builds a candidate; it does not install or accept a release.
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

BASE_SHA256 = "c3841266725dd7be99b3226916b2bb7756ca4139e77216c4c070be86a7524f33"
SITE = Path("runtime/lib/python3.12/site-packages")
RUNTIME_DELTAS = {
    "aivan": frozenset({"src/aivan/integrations/giraffe_db.py"}),
    "database": frozenset({"src/giraffe_db/db/canonical_language.py"}),
}
RUNTIME_PREFIXES = ("src/", "api/", "generators/", "alembic/")


def verify_component(source: Path, name: str, component: dict, *, payload_files: dict) -> list[dict]:
    """Select only the scoped repair, rejecting any other runtime difference."""
    if name not in RUNTIME_DELTAS:
        raise ValueError("Unknown repair component")
    baseline = {path: digest for path, digest in component["included_source_files"].items()
                if path.startswith(RUNTIME_PREFIXES)}
    selected = set()
    for directory in ("src", "api", "generators", "alembic"):
        root = source / directory
        if root.is_symlink():
            raise ValueError("Source directory links are not permitted")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Source links are not permitted")
            if path.is_file() and "__pycache__" not in path.parts:
                selected.add(str(path.relative_to(source)))
    if selected != baseline.keys():
        raise ValueError("Runtime source additions or removals are not selected")
    changed = {path for path, digest in baseline.items()
               if build.digest(build.safe_source_file(source, path)) != digest}
    if changed != RUNTIME_DELTAS[name]:
        raise ValueError("Runtime difference is not the exact selected repair")
    rows = []
    for path in sorted(changed):
        targets = [str(SITE / path.removeprefix("src/"))]
        if payload_files.get(targets[0]) != baseline[path]:
            raise ValueError("Declared installed module differs from source baseline")
        if name == "database":
            asset = "provider-assets/giraffe-db/" + path
            if asset in payload_files:
                if payload_files[asset] != baseline[path]:
                    raise ValueError("Declared source mirror differs from source baseline")
                targets.append(asset)
        rows.append({"component": name, "source_path": path, "targets": targets,
            "base_sha256": baseline[path], "candidate_sha256": build.digest(source / path),
            "_source": source})
    return rows


def apply_replacements(payload: Path, rows: list[dict]) -> None:
    """Check every source and destination before modifying any disposable file."""
    for row in rows:
        source = build.safe_source_file(row["_source"], row["source_path"])
        if build.digest(source) != row["candidate_sha256"]:
            raise ValueError("Selected source changed after verification")
        for relative in row["targets"]:
            target = build.safe_source_file(payload, relative)
            if build.digest(target) != row["base_sha256"]:
                raise ValueError("Installed baseline does not match selected source")
    for row in rows:
        for relative in row["targets"]:
            # Keep verified installed permissions, not operator checkout modes.
            shutil.copyfile(row["_source"] / row["source_path"], payload / relative)


def extract_base(installer: Path, destination: Path) -> tuple[dict, str]:
    if build.digest(installer) != BASE_SHA256:
        raise ValueError("Frozen integrated installer checksum mismatch")
    pieces = installer.read_bytes().split(b"__MYAIVAN_PAYLOAD__\n", 1)
    if len(pieces) != 2:
        raise ValueError("Frozen installer payload marker missing")
    header, archive = pieces
    archive_sha = hashlib.sha256(archive).hexdigest()
    if archive_sha.encode() not in header:
        raise ValueError("Frozen archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        names = set()
        for member in stream.getmembers():
            name = Path(member.name)
            normalized = str(name)
            if name.is_absolute() or ".." in name.parts or normalized in names \
                    or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe or duplicate frozen archive member")
            names.add(normalized)
        stream.extractall(destination, filter="data")
    manifest = json.loads((destination / "manifest.json").read_text())
    actual = inventory(destination)
    actual.pop("manifest.json", None)
    if actual != manifest["files"]:
        raise ValueError("Frozen payload inventory mismatch")
    return manifest, archive_sha


def distribution(site: Path, pattern: str) -> Path:
    matches = list(site.glob(pattern))
    if len(matches) != 1 or not matches[0].is_dir() or matches[0].is_symlink():
        raise ValueError("Expected one frozen distribution metadata directory")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-installer", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--database-revision", required=True)
    parser.add_argument("--database-tree", required=True)
    parser.add_argument("--database-source-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.release):
        raise ValueError("Invalid release name")
    source, database = args.source.resolve(), args.database_source.resolve()
    evidence = {"aivan": build.source_evidence(source, args.revision, args.tree),
        "database": build.source_evidence(database, args.database_revision, args.database_tree,
                                          args.database_source_manifest)}
    if any(item["modified"] for item in evidence.values()):
        raise ValueError("Both selected source identities must be exact and unmodified")
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"myaivan-{args.release}-linux-x86_64.run"
    if any(path.exists() for path in (destination, destination.with_suffix(".tar.gz"),
                                      destination.with_suffix(".run.sha256"))):
        raise ValueError("Refusing to overwrite an existing release artifact")
    with tempfile.TemporaryDirectory(prefix="myaivan-runtime-repair-", dir=args.output) as temporary:
        payload = Path(temporary) / "payload"
        payload.mkdir()
        base, archive_sha = extract_base(args.base_installer, payload)
        if build.digest(source / "installer/requirements.lock") != base["requirements_lock_sha256"]:
            raise ValueError("Frozen dependency lock changed")
        rows = verify_component(source, "aivan", base["components"]["aivan"], payload_files=base["files"])
        rows += verify_component(database, "database", base["components"]["database"], payload_files=base["files"])
        apply_replacements(payload, rows)
        public_rows = [{key: value for key, value in row.items() if key != "_source"} for row in rows]
        provenance = {"build_kind": "offline-integrated-runtime-repair", "release": args.release,
            "base_release": base["release"], "base_installer_sha256": BASE_SHA256,
            "base_archive_sha256": archive_sha, "base_manifest_sha256": build.digest(payload / "manifest.json"),
            "base_derived_build": json.loads((payload / "derived-build.json").read_text()),
            "selected_component_sources": evidence, "runtime_delta": public_rows,
            "builder_sha256": build.digest(Path(__file__)),
            "runtime_dependencies": "Byte-identical frozen native runtime, dependency locks and unrelated components; no downloads, installs or wheel rebuilds",
            "abi_evidence": "Prior base report retained because all native bytes/layout are unchanged; not a new host execution or ABI test",
            "acceptance": "Packaging identity/inventory only; actual API, MySQL, browser and deployment results are separate"}
        site = payload / SITE
        distributions = [distribution(site, "aivan-*.dist-info"), distribution(site, "giraffe_db-*.dist-info")]
        for metadata in distributions:
            write_json(metadata / "DERIVED-BUILD.json", provenance)
            update_record(site, metadata)
        write_json(payload / "derived-build.json", provenance)
        sbom = json.loads((payload / "sbom.json").read_text())
        matched = set()
        for entry in sbom:
            name = entry["name"].lower().replace("_", "-")
            if name in {"aivan", "giraffe-db"}:
                entry["modified_from_frozen_distribution"] = True
                entry["provenance_file"] = "derived-build.json"
                matched.add(name)
        if matched != {"aivan", "giraffe-db"}:
            raise ValueError("Frozen SBOM omits a repaired distribution")
        write_json(payload / "sbom.json", sbom)
        manifest = copy.deepcopy(base)
        manifest.update(release=args.release, build_kind=provenance["build_kind"],
            base_installer_sha256=BASE_SHA256, deployment_candidate=evidence["aivan"])
        for name in ("aivan", "database"):
            component = manifest["components"][name]
            component["base_source_evidence"] = copy.deepcopy(base["components"][name])
            component["selected_source_candidate"] = evidence[name]
            component["modified"] = True
            component["revision_semantics"] = "Base wheel provenance retained; exact repaired runtime source is selected_source_candidate"
            selected = [row for row in public_rows if row["component"] == name]
            component["derived_runtime_delta"] = selected
            for row in selected:
                for field in ("included_source_files", "verified_build_input_files"):
                    component[field][row["source_path"]] = row["candidate_sha256"]
        current = inventory(payload)
        current.pop("manifest.json")
        changed = {name for name in base["files"].keys() | current.keys()
                   if base["files"].get(name) != current.get(name)}
        permitted = {target for row in rows for target in row["targets"]}
        permitted.update({"derived-build.json", "sbom.json"})
        for metadata in distributions:
            permitted.update(str((metadata / name).relative_to(payload)) for name in ("DERIVED-BUILD.json", "RECORD"))
        if changed != permitted:
            raise ValueError("Payload changes differ from the exact Python and provenance selection")
        manifest["files"] = current
        write_json(payload / "manifest.json", manifest)
        build.write_installer(payload, destination)
        for name in ("manifest", "sbom", "derived-build"):
            shutil.copy2(payload / f"{name}.json", args.output / f"{args.release}-{name}.json")
        print(json.dumps({"installer": str(destination), "bytes": destination.stat().st_size,
            "sha256": build.digest(destination), "selected_component_sources": evidence,
            "runtime_delta": public_rows, "changed_payload_files": sorted(changed),
            "native_runtime": "Byte-identical base; no dependency or ABI rebuild",
            "deployment": "NOT_RUN"}, indent=2))


if __name__ == "__main__":
    main()
