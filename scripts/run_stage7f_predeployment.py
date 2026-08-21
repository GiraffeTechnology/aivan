#!/usr/bin/env python3
"""Run the read-only Stage 7F production-predeployment gate.

This command validates an immutable candidate, a secret-bearing environment
file without printing or hashing secret values, the approved CTYun/Singapore
topology descriptor, and the current database schema. It never deploys,
migrates, restarts services, changes ports, or emits production-acceptance
evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import create_engine

from aivan.db.schema_validation import schema_issues


EVIDENCE_CLASS = "production_predeployment"
PRODUCTION_ACCEPTANCE = False
DATABASE_PROFILE = "sqlite:///./data/aivan.db"
REQUIRED_ORIGIN = "https://myaivan.com"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CANDIDATE_PATTERN = re.compile(r"^[0-9a-f]{40}$")
LOCK_FILES = (
    "pyproject.toml",
    "uv.lock",
    "integrations/openclaw-aivan-plugin/package-lock.json",
)
REQUIRED_OBSERVATIONS = (
    "target_path_verified",
    "service_identity_verified",
    "service_health_ok",
    "bridge_active",
    "bridge_health_ok",
    "protected_ports_preserved",
    "database_profile_verified",
    "language_provider_real",
    "outbound_render_verified",
    "proofreading_boundary_verified",
)
FORBIDDEN_DESCRIPTOR_KEY_PARTS = (
    "password",
    "private_key",
    "access_key",
    "secret",
    "token",
    "api_key",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest_bytes(raw.encode("utf-8"))


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsey(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def _has_value(environment: dict[str, str | None], key: str) -> bool:
    return bool((environment.get(key) or "").strip())


def _descriptor_has_forbidden_keys(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in FORBIDDEN_DESCRIPTOR_KEY_PARTS):
                return True
            if _descriptor_has_forbidden_keys(child):
                return True
    elif isinstance(value, list):
        return any(_descriptor_has_forbidden_keys(item) for item in value)
    return False


def _load_topology(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("topology descriptor must be a JSON object")
    return parsed


def _database_url(repository_root: Path, configured_url: str) -> str:
    if configured_url != DATABASE_PROFILE:
        return configured_url
    database_path = (repository_root / "data" / "aivan.db").resolve()
    return f"sqlite:///{database_path.as_posix()}"


def run_predeployment_gate(
    *,
    repository_root: Path,
    candidate_commit: str,
    environment_file: Path,
    topology_file: Path,
    output_path: Path,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    candidate_commit = candidate_commit.strip().lower()
    if not CANDIDATE_PATTERN.fullmatch(candidate_commit):
        raise ValueError("candidate_commit must be a full 40-character lowercase Git SHA")

    environment = dict(dotenv_values(environment_file, interpolate=False))
    topology = _load_topology(topology_file)
    checks: list[dict[str, str]] = []

    def check(code: str, passed: bool) -> None:
        checks.append({"code": code, "result": "passed" if passed else "failed"})

    check("descriptor_contains_no_secret_fields", not _descriptor_has_forbidden_keys(topology))
    check("environment_is_production", environment.get("AIVAN_ENV") == "production")
    check("candidate_matches_environment", environment.get("AIVAN_CANDIDATE_SHA") == candidate_commit)
    check("application_loopback_bind", environment.get("AIVAN_HOST") == "127.0.0.1")
    check("application_port_8765", environment.get("AIVAN_PORT") == "8765")
    check("fixed_database_profile", environment.get("AIVAN_DB_URL") == DATABASE_PROFILE)
    check(
        "singapore_egress_policy",
        environment.get("AIVAN_NON_CHINA_EGRESS_POLICY") == "abcdyi-sin",
    )
    origins = {
        origin.strip()
        for origin in (environment.get("AIVAN_CORS_ORIGINS") or "").split(",")
        if origin.strip()
    }
    check("cors_exact_origin", REQUIRED_ORIGIN in origins and "*" not in origins)
    check("human_approval_required", _truthy(environment.get("AIVAN_REQUIRE_HUMAN_APPROVAL")))
    check("external_model_api_disabled", _falsey(environment.get("AIVAN_EXTERNAL_MODEL_API_ENABLED")))
    check("external_model_auto_disabled", _falsey(environment.get("AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED")))
    check("stub_suppliers_disabled", _falsey(environment.get("AIVAN_ALLOW_STUB_SUPPLIERS")))
    check("openclaw_mock_disabled", _falsey(environment.get("OPENCLAW_MOCK_MODE")))
    check(
        "api_auth_configured",
        _has_value(environment, "AIVAN_API_KEY")
        or _has_value(environment, "AIVAN_TENANT_API_KEYS"),
    )
    check("tenant_identity_configured", _has_value(environment, "AIVAN_TENANT_ID"))
    check("ui_actor_configured", _has_value(environment, "AIVAN_UI_ACTOR_ID"))
    session_secret = environment.get("AIVAN_UI_SESSION_SECRET") or ""
    check("ui_session_secret_minimum_length", len(session_secret) >= 32)
    check("openclaw_endpoint_configured", _has_value(environment, "OPENCLAW_BASE_URL"))
    check("openclaw_auth_configured", _has_value(environment, "OPENCLAW_API_KEY"))
    check("giraffe_db_endpoint_configured", _has_value(environment, "GIRAFFE_DB_BASE_URL"))
    check(
        "giraffe_db_auth_configured",
        _has_value(environment, "GIRAFFE_DB_SERVICE_AUTH_SECRET"),
    )
    check("topology_profile", topology.get("profile") == "ctyun-aivan-myaivan")
    check("topology_cloud", topology.get("cloud") == "ctyun-cn")
    check("fixed_install_path", topology.get("install_path") == "/opt/giraffe/aivan")
    check("fixed_service_name", topology.get("service_name") == "myaivan.service")
    check("topology_loopback_bind", topology.get("bind_host") == "127.0.0.1")
    check("topology_port_8765", topology.get("bind_port") == 8765)
    check("topology_database_profile", topology.get("database_profile") == DATABASE_PROFILE)
    check("topology_bridge", topology.get("non_china_egress_bridge") == "abcdyi-sin")
    check(
        "protected_port_owners",
        topology.get("protected_port_owners") == {"443": "nginx", "8443": "stalwart"},
    )
    bridge = topology.get("reverse_bridge") or {}
    check(
        "reverse_bridge_contract",
        bridge
        == {
            "remote_host_profile": "abcdyi-sin",
            "remote_bind": "127.0.0.1",
            "remote_port": 18765,
            "health_path": "/health",
        },
    )
    check("local_model_matches_profile", topology.get("expected_local_model") == environment.get("OLLAMA_MODEL"))
    check("language_skill_enabled", _truthy(environment.get("AIVAN_LANGUAGE_SKILL_ENABLED")))
    check(
        "language_provider_not_mock",
        (environment.get("AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER") or "").strip().lower()
        not in {"", "mock"},
    )
    check(
        "language_backend_declared",
        _has_value(environment, "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL")
        or _has_value(environment, "AIVAN_LANGUAGE_SKILL_EXPECTED_BACKEND"),
    )
    check("qwen_proofreading_enabled", _truthy(environment.get("AIVAN_TRANSLATION_PROOFREAD_ENABLED")))
    check("qwen_proofreader_exact", environment.get("OLLAMA_MODEL") == "qwen3.5:9b")

    observations = topology.get("observations") or {}
    observation_digests = topology.get("observation_digests") or {}
    for observation in REQUIRED_OBSERVATIONS:
        check(f"observation_{observation}", observations.get(observation) is True)
        check(
            f"observation_digest_{observation}",
            bool(SHA256_PATTERN.fullmatch(str(observation_digests.get(observation, "")))),
        )

    configured_database = environment.get("AIVAN_DB_URL") or ""
    issues: list[str] = []
    if configured_database:
        engine = create_engine(_database_url(repository_root, configured_database))
        try:
            issues = schema_issues(engine)
        finally:
            engine.dispose()
    check("database_schema_current", bool(configured_database) and not issues)

    lock_digests = {
        name: _file_digest(repository_root / name)
        for name in LOCK_FILES
        if (repository_root / name).is_file()
    }
    check("all_dependency_locks_present", set(lock_digests) == set(LOCK_FILES))
    passed = all(item["result"] == "passed" for item in checks)
    environment_profile = {
        "config_keys_sha256": _digest_json(sorted(environment)),
        "configured_key_count": len(environment),
        "secret_values_recorded": False,
        "environment": environment.get("AIVAN_ENV"),
        "host": environment.get("AIVAN_HOST"),
        "port": environment.get("AIVAN_PORT"),
        "database_profile": environment.get("AIVAN_DB_URL"),
        "non_china_egress_policy": environment.get("AIVAN_NON_CHINA_EGRESS_POLICY"),
        "local_model": environment.get("OLLAMA_MODEL"),
    }
    evidence = {
        "schema_version": 1,
        "stage": "7F-predeployment",
        "evidence_class": EVIDENCE_CLASS,
        "production_acceptance": PRODUCTION_ACCEPTANCE,
        "candidate_commit": candidate_commit,
        "created_at": _utcnow(),
        "status": "passed" if passed else "failed_closed",
        "environment_profile": environment_profile,
        "topology_descriptor_sha256": _file_digest(topology_file),
        "dependency_lock_digests": lock_digests,
        "schema_issue_count": len(issues),
        "schema_issues_sha256": _digest_json(issues),
        "checks": checks,
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
    parser.add_argument("--candidate-commit")
    parser.add_argument("--environment-file", type=Path)
    parser.add_argument("--topology-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(
            json.dumps(
                {
                    "evidence_class": EVIDENCE_CLASS,
                    "production_acceptance": PRODUCTION_ACCEPTANCE,
                    "required_origin": REQUIRED_ORIGIN,
                    "database_profile": DATABASE_PROFILE,
                    "required_observations": list(REQUIRED_OBSERVATIONS),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    missing = [
        name
        for name, value in (
            ("--candidate-commit", args.candidate_commit),
            ("--environment-file", args.environment_file),
            ("--topology-file", args.topology_file),
            ("--output", args.output),
        )
        if value is None
    ]
    if missing:
        parser.error(f"required unless --list is used: {', '.join(missing)}")
    result = run_predeployment_gate(
        repository_root=args.repository_root,
        candidate_commit=args.candidate_commit,
        environment_file=args.environment_file,
        topology_file=args.topology_file,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "candidate_commit": result["candidate_commit"],
                "evidence_file": str(args.output.resolve()),
                "production_acceptance": False,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
