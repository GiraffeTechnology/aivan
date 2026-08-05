from __future__ import annotations

import json
import subprocess

from scripts.run_stage6_acceptance import (
    CONFIG_PROFILES,
    EVIDENCE_CLASS,
    REQUIRED_CONSECUTIVE_RUNS,
    build_command,
    build_environment_profile,
    run_stage6a_preflight,
)


def _repository_fixture(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='stage6-test'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


def test_stage6_runner_requires_five_successes_and_appends_safe_evidence(
    tmp_path, monkeypatch
):
    repository = _repository_fixture(tmp_path)
    monkeypatch.setenv("AIVAN_API_KEY", "must-never-enter-evidence")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, 0, stdout="passed output", stderr=""
        )

    ticks = iter(range(20))
    output = tmp_path / "evidence" / "stage6.jsonl"
    result = run_stage6a_preflight(
        repository_root=repository,
        output_path=output,
        candidate_commit="candidate-123",
        config_profile="stage6a-ci",
        runner=runner,
        clock=lambda: next(ticks),
    )

    assert result["status"] == "passed"
    assert result["consecutive_passes"] == REQUIRED_CONSECUTIVE_RUNS == 5
    assert len(calls) == 5
    assert all(call[0] == build_command() for call in calls)
    stored = json.loads(output.read_text().strip())
    assert stored["evidence_class"] == EVIDENCE_CLASS
    assert stored["production_acceptance"] is False
    assert stored["candidate_commit"] == "candidate-123"
    assert stored["environment_profile"]["config_profile"] == "stage6a-ci"
    assert stored["environment_profile"]["execution_context"] == "ci"
    assert stored["environment_profile"]["external_network_required"] is False
    assert stored["environment_profile"]["production_services_modified"] is False
    assert stored["environment_profile"]["python_version"]
    assert stored["environment_profile"]["platform_system"]
    assert stored["dependency_lock_digests"].keys() == {
        "pyproject.toml",
        "uv.lock",
    }
    assert "passed output" not in output.read_text()
    assert "must-never-enter-evidence" not in output.read_text()
    assert len(stored["attempts"][0]["stdout_sha256"]) == 64
    assert stored["evidence_summary"] == {
        "attempted_runs": 5,
        "passed_runs": 5,
        "failed_runs": 0,
        "consecutive_passes": 5,
        "result": "passed",
    }


def test_stage6_runner_stops_on_failure_and_resets_consecutive_count(tmp_path):
    repository = _repository_fixture(tmp_path)
    outcomes = iter((0, 0, 7, 0, 0))

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command, next(outcomes), stdout="", stderr="safe failure"
        )

    ticks = iter(range(20))
    output = tmp_path / "stage6.jsonl"
    result = run_stage6a_preflight(
        repository_root=repository,
        output_path=output,
        candidate_commit="candidate-failed",
        runner=runner,
        clock=lambda: next(ticks),
    )

    assert result["status"] == "failed_reset_required"
    assert result["consecutive_passes"] == 0
    assert [attempt["returncode"] for attempt in result["attempts"]] == [0, 0, 7]
    assert len(output.read_text().splitlines()) == 1
    assert result["evidence_summary"]["attempted_runs"] == 3
    assert result["evidence_summary"]["passed_runs"] == 2
    assert result["evidence_summary"]["failed_runs"] == 1


def test_environment_profile_is_allowlisted_and_contains_no_host_identity():
    assert tuple(CONFIG_PROFILES) == (
        "stage6a-local",
        "stage6a-ci",
        "stage6a-candidate-preflight",
    )
    profile = build_environment_profile("stage6a-local")
    assert profile["config_profile"] == "stage6a-local"
    assert "hostname" not in profile
    assert "username" not in profile
    assert "environment_variables" not in profile
