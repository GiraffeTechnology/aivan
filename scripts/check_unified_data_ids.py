#!/usr/bin/env python3
"""Cross-repository scanner for the unified data-ID contract.

Fails closed when a retired giraffe-db record id (``<ENTITY>_SYN_<digits>``)
survives anywhere in runtime code, generated data, docs, fixtures or examples.
Also reports ambiguous ad-hoc placeholders (``supplier_001``, ``mock_supplier``,
...) as warnings: those strings are frequently legitimate non-DB identifiers
(messaging sender ids, conversation ids, internal report ids), so they are
advisory by default and only fail the build under ``--strict``.

Severities
----------
* ``error``   -- retired DB-record id. Always non-zero exit (this is the P0 gate).
* ``warning`` -- ad-hoc placeholder. Non-zero exit only with ``--strict``.

Legacy strings are permitted inside explicitly named negative tests:
a path under ``tests/negative/``, a file named ``test_reject_legacy_ids.py``,
or any line carrying the inline marker ``legacy-id-ok``.

Usage::

    python scripts/check_unified_data_ids.py --repo /path/to/giraffe-db --strict
    python scripts/check_unified_data_ids.py --repo ./aivan --repo ./giraffe-agent
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Retired DB-record id format this contract replaces -> error severity.
ENTITY_PREFIXES = (
    "SUP", "PROD", "CAP", "CUST", "PREF", "RFQ", "QUOTE", "OBS", "RISK",
    "LINEAGE", "IMPORT",
)
LEGACY_DB_ID_RE = re.compile(r"\b(" + "|".join(ENTITY_PREFIXES) + r")_SYN_[0-9]{3,}\b")

# Ambiguous ad-hoc placeholders -> warning severity.
ADHOC_RE = re.compile(
    r"\b(supplier_001|product_001|rfq_001|quote_001|obs_001|risk_001"
    r"|mock_supplier|demo_supplier)\b"
)

NEGATIVE_TEST_MARKER = "legacy-id-ok"
NEGATIVE_TEST_FILENAMES = {"test_reject_legacy_ids.py"}
NEGATIVE_TEST_DIR_PART = f"{'tests'}/negative/"

SCAN_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".sql",
    ".yaml", ".yml", ".csv", ".sh", ".txt",
}
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "snapshots",
}

# Recommended fix shown per match.
FIX_ERROR = "replace with canonical GDB_SYN_V1_<ENTITY>_<NNNNNN> id (generators/id_convention.py)"
FIX_WARN = "use a canonical test id or isolate as a non-DB placeholder in tests/negative/"


@dataclass
class Finding:
    path: str
    line: int
    match: str
    severity: str
    fix: str


def _is_negative_test(path: Path, line: str) -> bool:
    posix = path.as_posix()
    if NEGATIVE_TEST_DIR_PART in posix:
        return True
    if path.name in NEGATIVE_TEST_FILENAMES:
        return True
    return NEGATIVE_TEST_MARKER in line


def _iter_files(repo: Path):
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in SCAN_SUFFIXES:
            continue
        yield p


def scan_repo(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _iter_files(repo):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Skip the scanner's own pattern definitions to avoid self-matching.
        if path.name == Path(__file__).name:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _is_negative_test(path, line):
                continue
            rel = path.relative_to(repo).as_posix()
            for m in LEGACY_DB_ID_RE.finditer(line):
                findings.append(Finding(rel, i, m.group(0), "error", FIX_ERROR))
            for m in ADHOC_RE.finditer(line):
                findings.append(Finding(rel, i, m.group(0), "warning", FIX_WARN))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan repos for legacy giraffe-db ids")
    parser.add_argument("--repo", action="append", default=[], type=Path,
                        help="Repo root to scan (repeatable). Defaults to this repo.")
    parser.add_argument("--strict", action="store_true",
                        help="Also fail on ad-hoc placeholder warnings.")
    args = parser.parse_args(argv)

    repos = args.repo or [Path(__file__).resolve().parent.parent]

    all_findings: list[Finding] = []
    for repo in repos:
        repo = repo.resolve()
        if not repo.exists():
            print(f"SKIP (missing): {repo}")
            continue
        repo_findings = scan_repo(repo)
        all_findings.extend(repo_findings)
        errors = sum(1 for f in repo_findings if f.severity == "error")
        warns = sum(1 for f in repo_findings if f.severity == "warning")
        print(f"== {repo} :: {errors} error(s), {warns} warning(s) ==")
        for f in repo_findings:
            print(f"  [{f.severity:7s}] {f.path}:{f.line}: {f.match!r} -> {f.fix}")

    n_err = sum(1 for f in all_findings if f.severity == "error")
    n_warn = sum(1 for f in all_findings if f.severity == "warning")
    print(f"\nTOTAL: {n_err} error(s), {n_warn} warning(s)")

    failed = n_err > 0 or (args.strict and n_warn > 0)
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
