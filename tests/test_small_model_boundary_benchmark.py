"""Small local model boundary benchmark harness tests (PRD §16, §18.3)."""
from __future__ import annotations

from aivan.telemetry.benchmark import (
    default_cases_path,
    load_cases,
    recommended_config,
    run_benchmark,
    to_markdown,
)
from aivan.telemetry.model_usage import ModelUsageRecorder, estimate_tokens


def test_benchmark_dataset_covers_all_tiers():
    cases = load_cases(default_cases_path())
    tiers = {c.tier for c in cases}
    assert {"simple", "medium", "noisy", "multilingual", "missing_field", "adversarial"} <= tiers
    assert len(cases) >= 20


def test_mode_a_zero_model_floor_passes_hard_thresholds():
    cases = load_cases(default_cases_path())
    report = run_benchmark(cases, "A")
    agg = report["aggregate"]
    # Zero-model floor: no external API, no outbound, no false-ready, no errors.
    assert agg["external_api_call_count"] == 0
    assert agg["outbound_before_approval_count"] == 0
    assert agg["false_ready_count"] == 0
    assert agg["error_count"] == 0
    assert report["hard_thresholds_passed"] is True
    # With no model and no skill, canonical destinations cannot be resolved, so
    # nothing should be marked ready.
    assert agg["ready_count"] == 0


def test_benchmark_never_reports_false_ready_or_outbound():
    cases = load_cases(default_cases_path())
    report = run_benchmark(cases, "A")
    for r in report["results"]:
        assert r["outbound_sent_before_approval"] is False
        if r["ready"]:
            assert r["destination_authoritative"] is True


def test_report_rendering_and_recommendation():
    cases = load_cases(default_cases_path())
    reports = {"A": run_benchmark(cases, "A")}
    md = to_markdown(reports)
    assert "Small Local Model Boundary Report" in md
    rec = recommended_config(reports)
    assert rec["recommended_private_domain_config"]["external_llm_api"] == "off"
    assert rec["recommended_private_domain_config"]["local_small_llm"]["canonical_fields"] == "forbidden"


def test_token_estimator_and_recorder():
    rec = ModelUsageRecorder()
    rec.record_call(task="t", provider="ollama", model="qwen3.5:0.8b", input_text="hello world", output_text="ok")
    assert rec.llm_call_count == 1
    assert rec.external_api_called is False
    assert rec.total_tokens > 0
    assert estimate_tokens("") == 0

    rec.record_call(task="t2", provider="openai", input_text="x")
    assert rec.external_api_called is True
    summary = rec.summary()
    assert summary["gltg_external_llm_api_called"] is False
