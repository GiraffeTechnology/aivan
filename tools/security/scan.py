#!/usr/bin/env python3
"""Fail-closed local security scans. Run from a clean repository checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from datetime import datetime, timezone

TOOLS = Path(__file__).resolve().parent
VERSIONS = {"semgrep": "1.179.0", "osv-scanner": "2.6.0", "zizmor": "1.30.1"}
SOURCE_SUFFIXES = {".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    require(path.is_file() and path.stat().st_size > 0, f"Missing or empty report: {path}")
    return json.loads(path.read_text())


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z", "--cached"], check=True, capture_output=True)
    paths = sorted(set(result.stdout.decode().rstrip("\0").split("\0")))
    require(bool(paths) and paths != [""], "No tracked files; refusing an empty scan")
    return paths


def run(command: list[str], report_dir: Path, name: str, timeout: int = 600, stdout: Path | None = None) -> int:
    """Keep logs and record failures, including launch failures and timeouts."""
    (report_dir / f"{name}.command.json").write_text(json.dumps(command, indent=2) + "\n")
    with (stdout or report_dir / f"{name}.stdout.log").open("w") as out, (report_dir / f"{name}.stderr.log").open("w") as err:
        result = subprocess.run(command, stdout=out, stderr=err, timeout=timeout, check=False,
                                env={**os.environ, "SEMGREP_ENABLE_VERSION_CHECK": "0", "SEMGREP_SEND_METRICS": "off"})
    (report_dir / f"{name}.exit-code.txt").write_text(f"{result.returncode}\n")
    return result.returncode


def check_version(tool: str, report_dir: Path) -> None:
    code = run([tool, "--version"], report_dir, f"{tool}-version", timeout=30)
    version = (report_dir / f"{tool}-version.stdout.log").read_text().strip()
    require(code == 0 and re.search(rf"(?<![\d.]){re.escape(VERSIONS[tool])}(?![\d.])", version) is not None,
            f"Expected {tool} {VERSIONS[tool]}, got {version!r} (exit {code})")


def normalized(path: str) -> str:
    return os.path.relpath(Path(path).resolve(), Path.cwd())


def verify_rules() -> dict:
    directory = TOOLS / "semgrep"
    manifest = read_json(directory / "manifest.json")
    require(hashlib.sha256((directory / "LICENSE").read_bytes()).hexdigest() == manifest["license_sha256"], "Vendored license digest mismatch")
    files = manifest["files"]
    require(len(files) == 79 and manifest["rules_per_language"] == {"python": 69, "javascript": 10, "typescript": 9},
            "Unexpected rule inventory; review rule updates and their coverage explicitly")
    expected = {item["path"] for item in files}
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.suffix in {".yaml", ".yml"}}
    require(actual == expected, "Rules missing or unmanifested rule files present")
    for item in files:
        require(hashlib.sha256((directory / item["path"]).read_bytes()).hexdigest() == item["sha256"],
                f"Rule digest mismatch: {item['path']}")
    return manifest


def reviewed_findings(scanner: str, results: list[dict]) -> tuple[list[dict], list[dict]]:
    """Retain raw findings; waive only reviewed rule/path/whole-file fingerprints."""
    exceptions = read_json(TOOLS / "reviewed-findings.json")[scanner]
    pending = list(results)
    waived = []
    for exception in exceptions:
        if scanner == "semgrep":
            matches = [r for r in pending if r["check_id"] == exception["rule"] and normalized(r["path"]) == exception["path"]]
        else:
            matches = [r for r in pending if r["ruleId"] == exception["rule"] and normalized(r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]) == exception["path"]]
        if not matches:
            continue
        path = Path(exception["path"])
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == exception["sha256"],
                f"Reviewed finding fingerprint changed: {exception['path']}; re-review required")
        require(len(matches) == exception["count"], f"Reviewed finding count changed: {exception['path']}")
        pending = [r for r in pending if r not in matches]
        waived.append(exception)
    return pending, waived


def semgrep(paths: list[str], reports: Path) -> dict:
    check_version("semgrep", reports)
    manifest = verify_rules()
    targets = [p for p in paths if Path(p).suffix in SOURCE_SUFFIXES]
    require(targets, "No Python/JavaScript/TypeScript targets")
    require(all(Path(p).is_file() and not Path(p).is_symlink() for p in targets), "Missing or symlinked source target")
    (reports / "expected-targets.json").write_text(json.dumps(targets, indent=2) + "\n")
    code = run(["semgrep", "scan", "--oss-only", "--config", str(TOOLS / "semgrep"),
                "--metrics", "off", "--disable-version-check", "--error", "--strict", "--no-git-ignore",
                "--disable-nosem", "--no-rewrite-rule-ids", "--max-target-bytes", "0", "--timeout", "30", "--timeout-threshold", "1",
                "--json-output", str(reports / "semgrep.json"),
                "--sarif-output", str(reports / "semgrep.sarif"), "--", *targets], reports, "semgrep")
    data = read_json(reports / "semgrep.json")
    sarif = read_json(reports / "semgrep.sarif")
    require(code in (0, 1), f"Semgrep scanner error, exit {code}")
    require(not data.get("errors"), f"Semgrep reported scan errors: {data.get('errors')}")
    require(not data.get("skipped_rules"), "Semgrep skipped rules")
    scanned = {normalized(p) for p in data["paths"]["scanned"]}
    require(scanned == set(targets), f"Incomplete Semgrep coverage: missing={sorted(set(targets) - scanned)}, unexpected={sorted(scanned - set(targets))}")
    require(len(sarif["runs"]) == 1 and len(sarif["runs"][0]["tool"]["driver"]["rules"]) == manifest["rule_files"],
            "Incomplete Semgrep rule report")
    require(sarif["runs"][0]["invocations"] and all(i.get("executionSuccessful") is True for i in sarif["runs"][0]["invocations"]), "Incomplete Semgrep invocation")
    require(bool(data["results"]) == (code == 1), "Semgrep --error exit status does not match its findings")
    unreviewed, waived = reviewed_findings("semgrep", data["results"])
    blocking = [r for r in unreviewed if r["extra"]["severity"] in {"WARNING", "ERROR"}]
    require(all(r["extra"]["severity"] in {"INFO", "WARNING", "ERROR"} for r in data["results"]), "Unknown Semgrep finding severity")
    summary = {"expected_files": len(targets), "scanned_files": len(scanned), "rules": manifest["rule_files"],
               "findings": len(data["results"]), "informational_findings": sum(r["extra"]["severity"] == "INFO" for r in data["results"]),
               "blocking_findings": len(blocking), "reviewed_findings": waived}
    (reports / "coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
    require(not blocking, f"Semgrep WARNING/ERROR findings: {len(blocking)}; see semgrep.json/sarif")
    return summary


def package_key(name: str, version: str, ecosystem: str) -> tuple[str, str, str]:
    if ecosystem == "PyPI":
        name = re.sub(r"[-_.]+", "-", name).lower()
    return ecosystem, name, version


def expected_packages(path: str) -> set[tuple[str, str, str]]:
    file = Path(path)
    if file.name == "uv.lock":
        data = tomllib.loads(file.read_text())
        packages = data["package"]
        require(all("version" in p for p in packages if "registry" in p.get("source", {})), f"Unversioned registry package in {path}")
        return {package_key(p["name"], p["version"], "PyPI") for p in packages if "registry" in p.get("source", {})}
    data = json.loads(file.read_text())
    require(data.get("lockfileVersion") in (2, 3), f"Unsupported npm lock format: {path}")
    packages = data["packages"]
    result = set()
    for location, package in packages.items():
        if not location or package.get("link"):
            continue
        require("version" in package, f"Unversioned package: {path}:{location}")
        name = package.get("name") or location.rsplit("node_modules/", 1)[-1]
        result.add(package_key(name, package["version"], "npm"))
    return result


def offline_databases(reports: Path) -> list[dict]:
    """Verify complete public ecosystem archives; never send project coordinates."""
    cache = os.environ.get("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY")
    require(bool(cache), "OSV offline database cache is not configured")
    snapshots = []
    for ecosystem in ("PyPI", "npm"):
        # OSV 2.6.0 delegates its cache to the pinned osv-scalibr matcher.
        directory = Path(cache) / "osv-scalibr" / ecosystem
        archive = directory / "all.zip"
        headers = directory / "download-headers.txt"
        require(archive.is_file() and not archive.is_symlink(), f"Missing offline database: {ecosystem}")
        require(headers.is_file(), f"Missing public database response metadata: {ecosystem}")
        response = headers.read_text()
        sizes = re.findall(r"(?im)^x-goog-stored-content-length:\s*(\d+)\s*$", response)
        require(sizes and int(sizes[-1]) == archive.stat().st_size,
                f"Incomplete public database download: {ecosystem}")
        require(zipfile.is_zipfile(archive), f"Invalid offline database archive: {ecosystem}")
        with zipfile.ZipFile(archive) as data:
            records = [n for n in data.namelist() if n.endswith(".json")]
            require(bool(records) and len(records) == len(set(records)), f"Empty or duplicate database records: {ecosystem}")
            require(data.testzip() is None, f"Corrupt offline database: {ecosystem}")
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        (reports / f"{ecosystem}-database-headers.txt").write_text(response)
        snapshots.append({"ecosystem": ecosystem,
                          "source": f"https://osv-vulnerabilities.storage.googleapis.com/{ecosystem}/all.zip",
                          "bytes": archive.stat().st_size, "records": len(records), "sha256": digest,
                          "verified_at": datetime.now(timezone.utc).isoformat()})
    (reports / "database-snapshots.json").write_text(json.dumps(snapshots, indent=2) + "\n")
    validator = os.environ.get("OSV_RECORD_VALIDATOR")
    require(bool(validator), "OSV record decoder is not configured")
    archives = [str(Path(cache) / "osv-scalibr" / ecosystem / "all.zip") for ecosystem in ("PyPI", "npm")]
    code = run([validator, *archives], reports, "osv-record-decoder")
    require(code == 0, f"Offline advisory record decoding failed: exit {code}")
    decoded = read_json(reports / "osv-record-decoder.stdout.log")
    require(decoded == {ecosystem: snapshots[index]["records"] for index, ecosystem in enumerate(("PyPI", "npm"))},
            "Offline advisory decoder did not cover every record")
    return snapshots


def osv(paths: list[str], reports: Path) -> dict:
    check_version("osv-scanner", reports)
    snapshots = offline_databases(reports)
    targets = [p for p in paths if Path(p).name in {"uv.lock", "package-lock.json"}]
    require(targets and any(Path(p).name == "uv.lock" for p in targets) and any(Path(p).name == "package-lock.json" for p in targets),
            "Expected both Python uv.lock and npm package-lock.json coverage")
    expected = {p: expected_packages(p) for p in targets}
    require(all(expected.values()), "Empty dependency inventory in lockfile")
    (reports / "expected-targets.json").write_text(json.dumps({p: sorted(v) for p, v in expected.items()}, indent=2) + "\n")
    command = ["osv-scanner", "scan", "source", "--offline", "--config", str(TOOLS / "osv-scanner.toml"),
               "--all-packages", "--all-vulns", "--format", "json"]
    for path in targets:
        command.extend(["--lockfile", path])
    code = run(command, reports, "osv", stdout=reports / "osv.json")
    data = read_json(reports / "osv.json")
    require(code in (0, 1), f"OSV scanner error, exit {code}")
    actual: dict[str, set] = {}
    findings = 0
    for source in data["results"]:
        path = normalized(source["source"]["path"])
        require(source["source"]["type"] == "lockfile", f"Unexpected source type: {path}")
        inventory = actual.setdefault(path, set())
        for item in source["packages"]:
            package = item["package"]
            inventory.add(package_key(package["name"], package["version"], package["ecosystem"]))
            findings += len(item.get("vulnerabilities", []))
    require(set(actual) == set(expected), f"Incomplete lockfile coverage: expected={sorted(expected)}, scanned={sorted(actual)}")
    for path, packages in expected.items():
        require(packages <= actual[path], f"Incomplete dependency coverage in {path}: {sorted(packages - actual[path])}")
    summary = {"lockfiles": len(targets), "packages_per_lockfile": {p: len(v) for p, v in actual.items()}, "findings": findings, "network_mode": "offline", "database_snapshots": snapshots}
    (reports / "coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
    require(code == 0 and findings == 0, f"OSV vulnerabilities found (exit {code}, {findings} package/advisory entries); see osv.json")
    return summary


def zizmor(paths: list[str], reports: Path) -> dict:
    check_version("zizmor", reports)
    targets = [p for p in paths if (p.startswith(".github/workflows/") and Path(p).suffix in {".yml", ".yaml"}) or Path(p).name in {"action.yml", "action.yaml"}]
    require(targets, "No GitHub Actions workflow/action targets")
    (reports / "expected-targets.json").write_text(json.dumps(targets, indent=2) + "\n")
    results = []
    for index, target in enumerate(targets):
        require(Path(target).is_file() and not Path(target).is_symlink(), f"Missing or symlinked Actions target: {target}")
        report = reports / f"zizmor-{index}.sarif"
        code = run(["zizmor", "--offline", "--strict-collection", "--no-config", "--no-ignores", "--format", "sarif", "--", target], reports, f"zizmor-{index}", stdout=report)
        data = read_json(report)
        require(code == 0 and len(data["runs"]) == 1, f"zizmor scanner error: {target}, exit {code}")
        invocation = data["runs"][0]["invocations"]
        require(invocation and all(i.get("executionSuccessful") is True for i in invocation), f"Incomplete zizmor scan: {target}")
        # SARIF mode intentionally exits zero on findings. The report is the gate.
        results.extend(data["runs"][0]["results"])
    unreviewed, waived = reviewed_findings("zizmor", results)
    summary = {"expected_files": len(targets), "scanned_files": len(targets), "findings": len(results), "blocking_findings": len(unreviewed),
               "reviewed_findings": waived, "mode": "offline regular persona"}
    (reports / "coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
    require(not unreviewed, f"zizmor findings: {len(unreviewed)}; see per-file SARIF reports")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scanner", choices=("semgrep", "osv", "zizmor"))
    args = parser.parse_args()
    reports = Path("security-reports") / args.scanner
    require(not reports.parent.is_symlink() and not reports.is_symlink(), "Report directory and its parent must not be symlinks")
    if reports.exists():
        shutil.rmtree(reports)
    reports.mkdir(parents=True)
    status = {"scanner": args.scanner, "success": False}
    try:
        status.update(globals()[args.scanner](tracked_files(), reports))
        status["success"] = True
    except (RuntimeError, OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        status["error"] = str(error)
        print(f"Security scan failed: {error}", file=sys.stderr)
    finally:
        (reports / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2))
    return 0 if status["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
