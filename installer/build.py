#!/usr/bin/env python3
"""Build an offline Linux x86_64 installer from independently pinned providers."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_tree_digest(entries):
    # SHA-1 is required for Git object compatibility; payload integrity uses SHA-256.
    root = {}
    for entry in entries:
        if entry["type"] != "blob":
            continue
        parts = entry["path"].split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (entry["mode"], entry["sha"])
    def encode(tree):
        records = []
        for name, value in tree.items():
            directory = isinstance(value, dict)
            mode, sha = ("40000", encode(value)) if directory else value
            records.append((name + ("/" if directory else ""), mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)))
        raw = b"".join(record for _, record in sorted(records))
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()
    return encode(root)


def safe_source_file(source: Path, name: str):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe pinned source path")
    path = source / relative
    if any(parent.is_symlink() for parent in [path, *path.parents] if parent != source and parent.is_relative_to(source)):
        raise ValueError("Pinned source links are not permitted")
    if not path.is_file():
        raise ValueError("Pinned source must be a regular file")
    return path


def source_evidence(source: Path, revision: str, expected_tree: str, source_manifest: Path | None = None):
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.fullmatch(r"[0-9a-f]{40}", expected_tree):
        raise ValueError("Component revisions and source trees must be full Git object IDs")
    if source_manifest:
        entries = json.loads(source_manifest.read_text())
        if git_tree_digest(entries) != expected_tree:
            raise ValueError("Upstream manifest does not reconstruct the expected Git tree")
        selected = {}
        prefixes = ("src/", "api/", "generators/", "alembic/")
        names = {"pyproject.toml", "README.md", "alembic.ini", "LICENSE", "LICENSE_NOTICE.md", "PATENT_NOTICE.md"}
        required = {entry["path"]: entry for entry in entries if entry["type"] == "blob" and (entry["path"].startswith(prefixes) or entry["path"] in names)}
        for name, entry in required.items():
            path = safe_source_file(source, name)
            content = path.read_bytes()
            if hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content, usedforsecurity=False).hexdigest() != entry["sha"]:
                raise ValueError(f"Pinned provider blob mismatch: {name}")
            selected[name] = digest(path)
        for directory in ("src", "api", "generators", "alembic"):
            for path in (source / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and not any(part.endswith(".egg-info") for part in path.parts) and str(path.relative_to(source)) not in required:
                    raise ValueError(f"Unpinned provider runtime input: {path.name}")
        return {"revision": revision, "upstream_tree": expected_tree, "source_manifest_sha256": digest(source_manifest), "included_source_files": selected, "modified": False}
    actual_revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual_revision != revision:
        raise ValueError("Source revision does not match the pinned Git commit")
    tree = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"], text=True).strip()
    if tree != expected_tree:
        raise ValueError(f"Source tree mismatch for {source.name}")
    tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode().split("\0")
    untracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "--others", "--exclude-standard", "src", "api"], text=True)
    if untracked.strip():
        raise ValueError("Untracked application runtime files are not permitted")
    hashes = {name: digest(safe_source_file(source, name)) for name in sorted(tracked) if name}
    changed = subprocess.check_output(["git", "-C", str(source), "diff", "--binary", "HEAD"], text=True)
    return {"revision": revision, "upstream_tree": tree, "tracked_content_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "patch_sha256": hashlib.sha256(changed.encode()).hexdigest(), "modified": bool(changed)}


def copy_python(source: Path, destination: Path):
    version = subprocess.check_output([str(source / "bin/python3"), "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True).strip()
    if version != "3.12":
        raise ValueError("This release lock targets CPython 3.12")
    (destination / "bin").mkdir(parents=True)
    shutil.copy2((source / "bin/python3").resolve(), destination / "bin/python3")
    library = destination / "lib"
    library.mkdir()
    shutil.copytree(source / "lib" / f"python{version}", library / f"python{version}", ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "tkinter", "idlelib", "turtledemo", "ensurepip"))
    for name in ("libpython3.12.so.1.0", "libpython3.12.so", "libpython3.so"):
        candidate = source / "lib" / name
        if candidate.exists():
            shutil.copy2(candidate, library / name, follow_symlinks=True)
    # GUI and deprecated crypt extensions are unused by these server services and
    # would otherwise require host-specific Tcl/Tk/libcrypt shared libraries.
    for pattern in ("_tkinter*.so", "_crypt*.so"):
        for extension in (library / f"python{version}/lib-dynload").glob(pattern):
            extension.unlink()
    return library / f"python{version}/site-packages"


def abi_report(payload: Path):
    floor = (0,)
    requirements = set()
    libstdcxx = set()
    dependencies = set()
    resolved_libraries = {}
    elf_count = 0
    library_dirs = [payload / "runtime/lib", *sorted((payload / "runtime/lib/python3.12/site-packages").glob("*.libs"))]
    loader_environment = {"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": ":".join(str(directory.resolve()) for directory in library_dirs)}
    for path in payload.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        elf_count += 1
        result = subprocess.check_output(["readelf", "--version-info", str(path)], text=True, stderr=subprocess.DEVNULL)
        for version in re.findall(r"\bGLIBC_([0-9.]+)", result):
            requirements.add(version)
            floor = max(floor, tuple(map(int, version.split("."))))
        libstdcxx.update(re.findall(r"\bGLIBCXX_([0-9.]+)", result))
        dynamic = subprocess.check_output(["readelf", "-d", str(path)], text=True, stderr=subprocess.DEVNULL)
        needed = re.findall(r"Shared library: \[([^]]+)\]", dynamic)
        dependencies.update(needed)
        if needed:
            resolved = subprocess.run(["ldd", str(path)], capture_output=True, text=True, env=loader_environment)
            if resolved.returncode or "not found" in resolved.stdout:
                raise ValueError(f"Unresolved ELF dependencies in {path.relative_to(payload)}")
            dependency_paths = []
            for line in resolved.stdout.splitlines():
                candidate = line.split("=>", 1)[-1].strip().rsplit(" (", 1)[0]
                if candidate.startswith("/"):
                    dependency_paths.append(candidate)
            for dependency_path in dependency_paths:
                dependency = Path(dependency_path).resolve()
                if dependency.is_relative_to(payload.resolve()):
                    location = "bundled"
                elif dependency.is_relative_to(Path("/usr/lib")) or dependency.is_relative_to(Path("/lib")) or dependency.is_relative_to(Path("/lib64")):
                    location = "system"
                else:
                    raise ValueError("Runtime depends on a library outside the package or base operating system")
                resolved_libraries[dependency.name] = location
    return {"os": "Linux", "architecture": "x86_64", "glibc_minimum_symbol_version": ".".join(map(str, floor)), "libstdcxx_minimum_symbol_version": max(libstdcxx, key=lambda value: tuple(map(int, value.split(".")))) if libstdcxx else None, "elf_files_scanned": elf_count, "needed_libraries": sorted(dependencies), "resolved_libraries": resolved_libraries, "all_elf_dependencies_resolved": True, "tested_host": platform.platform(), "older_host_execution": "not tested; symbol scan is a minimum, not a compatibility certification"}


def write_installer(payload: Path, destination: Path):
    archive = destination.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz", dereference=True) as tar:
        for path in sorted(payload.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()) or not all(ord(char) < 128 and char not in "\r\n" for char in str(path.relative_to(payload))):
                raise ValueError("Unsafe package file name or symlink")
            tar.add(path, arcname=str(path.relative_to(payload)), recursive=False)
    checksum = digest(archive)
    header = r'''#!/bin/sh
# MyAivan self-contained Linux installer. No Python, pip, uv or Docker required.
set -eu
umask 077
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo "This package requires Linux x86_64." >&2; exit 1
fi
if [ "${1:-}" = "--prefix" ]; then
  [ "$#" -ge 2 ] || { echo "--prefix requires a directory" >&2; exit 1; }
  PREFIX=$2; shift 2
else
  PREFIX="${HOME:?Set HOME or provide --prefix}/.local/share/myaivan"
fi
for TOOL in tail tar sha256sum mktemp awk; do
  command -v "$TOOL" >/dev/null || { echo "Missing base operating-system tool: $TOOL" >&2; exit 1; }
done
WORK=$(mktemp -d "${TMPDIR:-/tmp}/myaivan-install.XXXXXXXX")
trap 'rm -rf -- "$WORK"' EXIT HUP INT TERM
LINE=$(awk '/^__MYAIVAN_PAYLOAD__$/ {print NR + 1; exit}' "$0")
tail -n +"$LINE" "$0" > "$WORK/payload.tar.gz"
printf '%s  %s\n' '__ARCHIVE_SHA256__' "$WORK/payload.tar.gz" | sha256sum -c - >/dev/null
# Fail before extraction on absolute paths, parent traversal, links and special files.
tar -tzf "$WORK/payload.tar.gz" > "$WORK/names"
awk '(/^\// || /(^|\/)\.\.($|\/)/) {bad=1} END {exit bad}' "$WORK/names" || { echo "Unsafe archive path" >&2; exit 1; }
tar -tvzf "$WORK/payload.tar.gz" | awk 'substr($0,1,1) != "-" && substr($0,1,1) != "d" {bad=1} END {exit bad}' || { echo "Unsafe archive entry" >&2; exit 1; }
mkdir "$WORK/release"
tar --no-same-owner --no-same-permissions -xzf "$WORK/payload.tar.gz" -C "$WORK/release"
"$WORK/release/runtime/bin/python3" -B -I "$WORK/release/runtime.py" --prefix "$PREFIX" install --payload "$WORK/release" "$@"
exit $?
__MYAIVAN_PAYLOAD__
'''.replace("__ARCHIVE_SHA256__", checksum)
    with destination.open("wb") as stream:
        stream.write(header.encode())
        with archive.open("rb") as binary:
            shutil.copyfileobj(binary, stream)
    destination.chmod(0o755)
    archive.unlink()
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{digest(destination)}  {destination.name}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for component in ("aivan", "gltg", "database", "language", "abcdyi"):
        parser.add_argument(f"--{component}-source", type=Path, required=True)
        parser.add_argument(f"--{component}-revision", required=True)
        parser.add_argument(f"--{component}-tree", required=True)
        parser.add_argument(f"--{component}-manifest", type=Path)
    parser.add_argument("--python-root", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("Build on Linux x86_64")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.release):
        raise ValueError("Invalid release name")
    args.output.mkdir(parents=True, exist_ok=True)
    components = {}
    sources = {}
    for component in ("aivan", "gltg", "database", "language", "abcdyi"):
        sources[component] = getattr(args, f"{component}_source").resolve()
        components[component] = source_evidence(sources[component], getattr(args, f"{component}_revision"), getattr(args, f"{component}_tree"), getattr(args, f"{component}_manifest"))
    with tempfile.TemporaryDirectory(prefix="myaivan-build-", dir=args.output) as temporary:
        work = Path(temporary)
        payload = work / "payload"
        payload.mkdir()
        site = copy_python(args.python_root.resolve(), payload / "runtime")
        run(args.uv, "pip", "install", "--python", payload / "runtime/bin/python3", "--target", site, "--require-hashes", "--only-binary", ":all:", "-r", HERE / "requirements.lock")
        wheelhouse = work / "wheels"
        wheelhouse.mkdir()
        for component, source in sources.items():
            clean = work / "sources" / component
            clean.mkdir(parents=True)
            selected = components[component].get("included_source_files")
            if selected is None:
                tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode().split("\0")
                selected = [name for name in tracked if name and (name.startswith(("src/", "api/", "generators/", "alembic/")) or name in {"pyproject.toml", "README.md", "LICENSE", "LICENSE_NOTICE.md", "PATENT_NOTICE.md", "alembic.ini"})]
            for name in selected:
                destination_file = clean / name
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(safe_source_file(source, name), destination_file)
            if component == "abcdyi":
                # Its historical wheel also exports an older top-level Aivan.
                # Keep the independently pinned API/src namespace process-local.
                isolated = payload / "services/abcdyi"
                shutil.copytree(clean, isolated)
                if not (isolated / "api/main.py").is_file():
                    raise ValueError("Pinned abcdYi input is missing its fulfillment API")
            else:
                run(args.uv, "build", "--wheel", "--out-dir", wheelhouse, clean)
        wheels = sorted(wheelhouse.glob("*.whl"))
        run(args.uv, "pip", "install", "--python", payload / "runtime/bin/python3", "--target", site, "--no-deps", *wheels)
        # Upstream giraffe-db uses a root-level helper package omitted by its wheel.
        # Keep this same-provider runtime data out of the Aivan source repository.
        generators = sources["database"] / "generators"
        if generators.exists():
            shutil.copytree(generators, site / "generators", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        provider_assets = payload / "provider-assets/giraffe-db"
        provider_assets.mkdir(parents=True)
        shutil.copytree(sources["database"] / "alembic", provider_assets / "alembic", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(sources["database"] / "alembic.ini", provider_assets / "alembic.ini")
        for name in ("runtime.py", "bootstrap.py", "service.py", "abcdyi_service.py", "requirements.lock", "README.md"):
            shutil.copy2(HERE / name, payload / name)
        licenses = payload / "licenses"
        licenses.mkdir()
        for name, source in sources.items():
            license_files = list(source.glob("LICENSE*")) + list(source.glob("PATENT_NOTICE*"))
            if not license_files:
                raise ValueError(f"Missing source license: {name}")
            for license_file in license_files:
                if license_file.is_file():
                    shutil.copy2(license_file, licenses / f"{name}-{license_file.name}")
        shutil.copy2(args.python_root / "lib/python3.12/LICENSE.txt", licenses / "Python-LICENSE.txt")
        supplemental = json.loads((HERE / "licenses/sources.json").read_text())
        for filename, source_info in supplemental.items():
            if digest(HERE / "licenses" / filename) != source_info["sha256"]:
                raise ValueError("Supplemental dependency license checksum mismatch")
        shutil.copytree(HERE / "licenses", licenses / "third-party")
        # Offline import smoke verifies installed wheels, never a source checkout.
        run(payload / "runtime/bin/python3", "-B", "-I", "-c", "import aivan.api.main,aivan.gpm.server,gltg.api.main,giraffe_db.api.main,giraffe_language_skill.api.main,py3langid,ctranslate2,sentencepiece; print('Offline runtime imports passed')", cwd=work, env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        run(payload / "runtime/bin/python3", "-B", "-I", payload / "abcdyi_service.py", "verify-import",
            cwd=work, env={"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                          "SECRET_KEY": secrets.token_urlsafe(48)})
        sbom = [{"name": "abcdyi", "version": components["abcdyi"]["revision"],
                 "license": "See independently supplied component license",
                 "license_files": [str(path.relative_to(payload)) for path in licenses.glob("abcdyi-*")]}]
        for dist in importlib.metadata.distributions(path=[str(site)]):
            sbom.append({"name": dist.metadata["Name"], "version": dist.version, "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", "See bundled distribution metadata/licenses"), "license_files": [str(file) for file in (dist.files or []) if any(token in str(file).lower() for token in ("license", "copying", "notice"))]})
        for entry in sbom:
            if not entry["license_files"]:
                matching = [f"licenses/third-party/{filename}" for filename in supplemental if filename.startswith(f"{entry['name'].lower()}-{entry['version']}-")]
                if not matching:
                    raise ValueError(f"No license text for installed dependency {entry['name']}")
                entry["license_files"] = matching
        (payload / "sbom.json").write_text(json.dumps(sorted(sbom, key=lambda item: item["name"].lower()), indent=2))
        # Remove build-generated caches; every byte in the final payload is inventoried.
        for cache in payload.rglob("__pycache__"):
            shutil.rmtree(cache)
        manifest = {"format": 1, "release": args.release, "components": components, "python_version": platform.python_version(), "abi": abi_report(payload), "wheels": {wheel.name: digest(wheel) for wheel in wheels}, "requirements_lock_sha256": digest(HERE / "requirements.lock"), "files": {str(path.relative_to(payload)): digest(path) for path in sorted(payload.rglob("*")) if path.is_file()}}
        (payload / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        destination = args.output / f"myaivan-{args.release}-linux-x86_64.run"
        write_installer(payload, destination)
        shutil.copy2(payload / "manifest.json", args.output / f"{args.release}-manifest.json")
        shutil.copy2(payload / "sbom.json", args.output / f"{args.release}-sbom.json")
        print(json.dumps({"installer": str(destination), "sha256": digest(destination), "size_bytes": destination.stat().st_size, "abi": manifest["abi"]}, indent=2))


if __name__ == "__main__":
    main()
