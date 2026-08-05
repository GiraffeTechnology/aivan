from __future__ import annotations

import json
import subprocess

from scripts.run_stage6_acceptance import (
    EVIDENCE_CLASS,
    REQUIRED_CONSECUTIVE_RUNS,
    build_command,
    run_stage6a_preflight,
)


def _repository_fixture(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='stage6-test'\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    return tmp_path


def test_stage6_runner_requires_five_successes_and_appends_safe_evidence(tmp_path):
    repository = _repository_fixture(tmp_path)
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
    assert stored["dependency_lock_digests"].keys() == {
        "pyproject.toml",
        "uv.lock",
    }
    assert "passed output" not in output.read_text()
    assert len(stored["attempts"][0]["stdout_sha256"]) == 64


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

