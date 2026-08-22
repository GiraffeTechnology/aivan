"""Run the non-production Stage 6A five-run gate and append safe JSON evidence.

This runner deliberately cannot issue production-acceptance evidence. Real
channel receipts, CTYun deployment checks, backup restores, and supervisor
sign-off remain external gates described by the Stage 6 PRD.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REQUIRED_CONSECUTIVE_RUNS = 5
EVIDENCE_CLASS = "automated_preflight"
CONFIG_PROFILES = {
    "stage6a-local": {
        "execution_context": "local",
        "external_network_required": False,
        "production_services_modified": False,
    },
    "stage6a-ci": {
        "execution_context": "ci",
        "external_network_required": False,
        "production_services_modified": False,
    },
    "stage6a-candidate-preflight": {
        "execution_context": "candidate_preflight",
        "external_network_required": False,
        "production_services_modified": False,
    },
}
STAGE6A_TESTS = (
    "tests/test_stage1_unified_contract.py",
    "tests/test_stage1_3_tenant_isolation.py",
    "tests/test_stage2_roles.py",
    "tests/test_stage2_approval_rbac.py",
    "tests/test_stage4_relay.py",
    "tests/test_stage5a_event_correction.py",
    "tests/test_stage5a_migration.py",
    "tests/test_llm_token_guard.py",
    "tests/test_stage7_delivery_safety.py",
)
LOCK_FILES = (
    "pyproject.toml",
    "uv.lock",
    "integrations/openclaw-aivan-plugin/package-lock.json",
)
CANDIDATE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_digest(value: str | bytes | None) -> str:
    if value is None:
        raw = b""
    elif isinstance(value, bytes):
        raw = value
    else:
        raw = value.encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()


def build_command(python_executable: str = sys.executable) -> list[str]:
    return [
        python_executable,
        "-m",
        "pytest",
        "-q",
        *STAGE6A_TESTS,
        "--tb=short",
    ]


def build_environment_profile(config_profile: str) -> dict:
    """Return a reproducible descriptor without host identity or env values."""

    if config_profile not in CONFIG_PROFILES:
        raise ValueError(f"Unsupported Stage 6A config profile: {config_profile}")
    return {
        "config_profile": config_profile,
        **CONFIG_PROFILES[config_profile],
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
    }


def run_stage6a_preflight(
    *,
    repository_root: Path,
    output_path: Path,
    candidate_commit: str,
    config_profile: str = "stage6a-local",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    repository_root = repository_root.resolve()
    output_path = output_path.resolve()
    normalized_candidate = candidate_commit.strip().lower()
    if normalized_candidate == "working-tree":
        if config_profile != "stage6a-local":
            raise ValueError(
                "working-tree evidence is allowed only for stage6a-local"
            )
    elif not CANDIDATE_COMMIT_PATTERN.fullmatch(normalized_candidate):
        raise ValueError("candidate_commit must be a full 40-character Git SHA")
    command = build_command()
    evidence = {
        "schema_version": 1,
        "stage": "6A",
        "evidence_class": EVIDENCE_CLASS,
        "production_acceptance": False,
        "candidate_commit": normalized_candidate,
        "environment_profile": build_environment_profile(config_profile),
        "required_consecutive_runs": REQUIRED_CONSECUTIVE_RUNS,
        "started_at": _utcnow(),
        "dependency_lock_digests": {
            name: _sha256_file(repository_root / name)
            for name in LOCK_FILES
            if (repository_root / name).is_file()
        },
        "test_paths": list(STAGE6A_TESTS),
        "attempts": [],
        "status": "running",
    }

    consecutive = 0
    for sequence in range(1, REQUIRED_CONSECUTIVE_RUNS + 1):
        started = clock()
        completed = runner(
            command,
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        duration_ms = max(0, round((clock() - started) * 1000))
        passed = completed.returncode == 0
        consecutive = consecutive + 1 if passed else 0
        evidence["attempts"].append(
            {
                "sequence": sequence,
                "result": "passed" if passed else "failed",
                "returncode": completed.returncode,
                "duration_ms": duration_ms,
                "stdout_sha256": _stream_digest(completed.stdout),
                "stderr_sha256": _stream_digest(completed.stderr),
            }
        )
        if not passed:
            break

    evidence["completed_at"] = _utcnow()
    evidence["consecutive_passes"] = consecutive
    evidence["status"] = (
        "passed"
        if consecutive == REQUIRED_CONSECUTIVE_RUNS
        else "failed_reset_required"
    )
    evidence["evidence_summary"] = {
        "attempted_runs": len(evidence["attempts"]),
        "passed_runs": sum(
            attempt["result"] == "passed" for attempt in evidence["attempts"]
        ),
        "failed_runs": sum(
            attempt["result"] == "failed" for attempt in evidence["attempts"]
        ),
        "consecutive_passes": consecutive,
        "result": evidence["status"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(evidence, ensure_ascii=False, sort_keys=True) + "\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-commit", default="working-tree")
    parser.add_argument(
        "--config-profile",
        choices=tuple(CONFIG_PROFILES),
        default="stage6a-local",
    )
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(json.dumps({
            "evidence_class": EVIDENCE_CLASS,
            "production_acceptance": False,
            "required_consecutive_runs": REQUIRED_CONSECUTIVE_RUNS,
            "config_profiles": list(CONFIG_PROFILES),
            "test_paths": list(STAGE6A_TESTS),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required unless --list is used")
    result = run_stage6a_preflight(
        repository_root=args.repository_root,
        output_path=args.output,
        candidate_commit=args.candidate_commit,
        config_profile=args.config_profile,
    )
    print(json.dumps({
        "status": result["status"],
        "consecutive_passes": result["consecutive_passes"],
        "evidence_file": str(args.output.resolve()),
    }, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
