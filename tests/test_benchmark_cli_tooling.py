"""Benchmark tooling tests: filters, progress/incremental output, timeouts (PR #29)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aivan.telemetry import benchmark
from aivan.telemetry.benchmark import (
    BenchmarkCase,
    filter_cases,
    format_progress_line,
    load_cases,
    run_benchmark,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cases():
    return load_cases(benchmark.default_cases_path())


# ── --max-cases / --case-id filtering ────────────────────────────────────────

def test_filter_cases_max_cases(cases):
    assert len(filter_cases(cases, max_cases=3)) == 3
    assert len(filter_cases(cases, max_cases=0)) == 0


def test_filter_cases_case_id(cases):
    ids = [c.case_id for c in cases[:2]]
    selected = filter_cases(cases, case_ids=ids)
    assert [c.case_id for c in selected] == ids
    # Unknown ids are ignored, not fatal.
    assert filter_cases(cases, case_ids=["does_not_exist"]) == []


def test_filter_cases_case_id_then_max(cases):
    ids = [c.case_id for c in cases[:4]]
    selected = filter_cases(cases, case_ids=ids, max_cases=2)
    assert [c.case_id for c in selected] == ids[:2]


def test_no_filters_unchanged(cases):
    # Requirement 7: default behavior unchanged when no filters are passed.
    assert filter_cases(cases) == cases


# ── progress line formatting ─────────────────────────────────────────────────

def test_format_progress_line_contains_fields():
    result = {
        "mode": "C", "case_id": "simple_zh_001", "tier": "simple",
        "started_at": "2026-07-02T00:00:00+00:00", "elapsed_seconds": 1.23,
        "provider": "ollama", "model": "qwen3.5:0.8b", "local_llm_tokens": 42,
        "failed": False, "fail_reasons": [],
    }
    line = format_progress_line(result)
    for token in ["[C]", "simple_zh_001", "tier=simple", "start=2026-07-02",
                  "elapsed=1.23s", "provider=ollama", "model=qwen3.5:0.8b", "tokens=42", "PASS"]:
        assert token in line

    result["failed"] = True
    result["fail_reasons"] = ["ollama_not_called"]
    assert "FAIL(ollama_not_called)" in format_progress_line(result)


# ── on_case incremental hook ─────────────────────────────────────────────────

def test_run_benchmark_calls_on_case_per_case(cases):
    seen = []
    report = run_benchmark(cases[:3], "A", on_case=seen.append)
    assert len(seen) == 3
    for r in seen:
        assert "case_id" in r
        assert "elapsed_seconds" in r and isinstance(r["elapsed_seconds"], (int, float))
        assert "started_at" in r
        assert "provider" in r
        assert "failed" in r and "fail_reasons" in r
    assert report["case_count"] == 3


# ── per-case timeout handling ────────────────────────────────────────────────

def test_per_case_timeout_marks_failed_and_continues(cases, monkeypatch):
    def slow_run_case(case, mode_key):
        time.sleep(1.0)
        return {"case_id": case.case_id, "tier": case.tier, "mode": mode_key, "ready": False}

    monkeypatch.setattr(benchmark, "run_case", slow_run_case)
    report = run_benchmark(cases[:2], "A", per_case_timeout=0.1)

    assert report["case_count"] == 2  # continued past the timeout
    assert report["aggregate"]["timeout_count"] == 2
    assert all(r["timed_out"] for r in report["results"])
    assert all(r["action"] == "timeout" for r in report["results"])
    assert report["hard_thresholds_passed"] is False
    assert any("timeout" in f for f in report["hard_threshold_failures"])


def test_fail_fast_stops_at_first_failure(cases, monkeypatch):
    def failing_run_case(case, mode_key):
        return {"case_id": case.case_id, "tier": case.tier, "mode": mode_key,
                "ready": False, "error": "boom", "timed_out": False}

    monkeypatch.setattr(benchmark, "run_case", failing_run_case)
    report = run_benchmark(cases[:5], "A", fail_fast=True)

    assert report["stopped_early"] is True
    assert report["case_count"] == 1  # stopped after the first failing case


def test_fail_fast_and_timeout_together(cases, monkeypatch):
    def slow_run_case(case, mode_key):
        time.sleep(1.0)
        return {"case_id": case.case_id, "tier": case.tier, "mode": mode_key, "ready": False}

    monkeypatch.setattr(benchmark, "run_case", slow_run_case)
    report = run_benchmark(cases[:3], "A", per_case_timeout=0.1, fail_fast=True)
    assert report["stopped_early"] is True
    assert report["case_count"] == 1
    assert report["results"][0]["timed_out"] is True


# ── end-to-end script: incremental JSONL + progress + max-cases ──────────────

def test_script_writes_incremental_jsonl_and_progress(tmp_path):
    out = tmp_path / "artifacts"
    proc = subprocess.run(
        [sys.executable, "scripts/benchmark_small_model_boundary.py",
         "--modes", "A", "--max-cases", "2", "--progress", "--out", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    # Progress lines on stdout.
    assert "[A]" in proc.stdout
    # Incremental JSONL written, one line per case.
    events = (out / "benchmark_events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 2
    first = json.loads(events[0])
    assert first["mode"] == "A"
    assert "elapsed_seconds" in first and "started_at" in first
    # Final reports still produced.
    assert (out / "small_model_boundary_report.json").exists()
    assert (out / "small_model_boundary_report.md").exists()
