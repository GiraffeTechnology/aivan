"""P1-1: benchmark proves real local-model usage from telemetry (PR #29)."""
from __future__ import annotations

import pytest

from aivan.llm import gateway
from aivan.llm.providers.ollama_provider import OllamaProvider
from aivan.telemetry import benchmark

_CANNED = {
    "category": "apparel",
    "product_type": "plaid shirt",
    "quantity": 5000,
    "destination": "Tokyo",
    "delivery_days": 45,
    "confidence": 0.9,
    "language": "en",
}


@pytest.fixture(autouse=True)
def _reset_provider():
    gateway.reset_provider()
    yield
    gateway.reset_provider()


@pytest.fixture
def _cases():
    return benchmark.load_cases(benchmark.default_cases_path())[:3]


def test_benchmark_mode_c_records_real_ollama_call(monkeypatch, _cases):
    monkeypatch.setattr(OllamaProvider, "complete_json", lambda self, *a, **k: dict(_CANNED))
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    report = benchmark.run_benchmark(_cases, "C")
    agg = report["aggregate"]

    assert agg["real_local_call_count"] == len(_cases)
    assert agg["mock_fallback_count"] == 0
    assert agg["external_api_call_count"] == 0
    assert agg["expected_local_provider"] == "ollama"
    assert agg["expected_local_model"] == "qwen3.5:0.8b"
    for r in report["results"]:
        assert r["real_local_call"] is True
        assert r["local_llm_model"] == "qwen3.5:0.8b"
        assert r["external_api_called"] is False
    assert report["hard_thresholds_passed"] is True


def test_benchmark_mode_c_fails_on_mock_fallback(monkeypatch, _cases):
    # Simulate the local model being unusable: the benchmark must not let this
    # pass as though ollama really ran (no silent mock fallback / success).
    monkeypatch.setattr(
        OllamaProvider, "complete_json",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("ollama down")),
    )
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    report = benchmark.run_benchmark(_cases, "C")
    assert report["hard_thresholds_passed"] is False
    assert report["aggregate"]["real_local_call_count"] < len(_cases)


def test_partial_local_failures_keep_integrity_thresholds_passing(monkeypatch):
    # The real CTYUN scenario: Ollama is alive (some cases succeed) but the tiny
    # 0.8b model fails structured extraction on others. Those are attempted-but-
    # failed calls (measured capability), NOT integrity violations, so hard
    # thresholds still pass while the failures are reported per case.
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise ValueError("qwen3.5:0.8b returned unparseable JSON")
        return dict(_CANNED)

    monkeypatch.setattr(OllamaProvider, "complete_json", flaky)
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    cases = benchmark.load_cases(benchmark.default_cases_path())[:4]
    report = benchmark.run_benchmark(cases, "C")
    agg = report["aggregate"]

    assert agg["real_local_call_count"] >= 1
    assert agg["local_call_failed_count"] >= 1
    assert agg["mock_fallback_count"] == 0
    assert agg["expected_local_call_missing_count"] == 0
    assert agg["external_api_call_count"] == 0
    assert report["hard_thresholds_passed"] is True  # integrity intact
    # Report explicitly separates integrity from capability.
    assert report["integrity_status"] == "pass"
    assert report["capability_status"] == "report_only"  # no --max-local-failure-rate
    assert report["local_call_failure_rate"] > 0
    # Failed case IDs + tiers are surfaced for diagnosis.
    assert report["local_call_failed_cases"]
    assert all("case_id" in c and "tier" in c for c in report["local_call_failed_cases"])
    # local_call_failed cases carry their provider error for diagnosis.
    failed = [r for r in report["results"] if r["local_call_status"] == "local_call_failed"]
    assert failed and all(r["provider_error"] for r in failed)
    assert all(r["used_provider"] == "ollama" for r in failed)


def test_max_local_failure_rate_gate(monkeypatch):
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise ValueError("bad json")
        return dict(_CANNED)

    monkeypatch.setattr(OllamaProvider, "complete_json", flaky)
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    cases = benchmark.load_cases(benchmark.default_cases_path())[:4]

    strict = benchmark.run_benchmark(cases, "C", max_local_failure_rate=0.3)
    assert strict["hard_thresholds_passed"] is False
    assert strict["capability_status"] == "fail"
    assert strict["integrity_status"] == "pass"  # capability gate only, integrity intact
    assert any("local_call_failure_rate" in f for f in strict["capability_failures"])

    calls["n"] = 0
    lenient = benchmark.run_benchmark(cases, "C", max_local_failure_rate=0.9)
    assert lenient["hard_thresholds_passed"] is True
    assert lenient["capability_status"] == "pass"


def _patch_no_llm_structuring(monkeypatch):
    """Simulate a pipeline path that never invokes the LLM gateway."""
    from aivan.schemas.requirement import BuyerRequirement

    def no_llm_structure(**kw):
        return BuyerRequirement(raw_text=kw.get("raw_text", ""), project_id="benchmark")

    monkeypatch.setattr(benchmark, "structure_customer_requirement_with_llm", no_llm_structure)


def test_intentionally_skipped_case_is_not_a_missing_call(monkeypatch):
    # A fixture-declared deterministic/no-model case that doesn't call the LLM is
    # intentionally_skipped, never expected_local_call_missing.
    from aivan.telemetry.benchmark import BenchmarkCase

    _patch_no_llm_structuring(monkeypatch)
    case = BenchmarkCase(case_id="det_only", tier="simple", input_language="en",
                         raw_text="5000 pcs to Osaka in 45 days", llm_required=False)
    report = benchmark.run_benchmark([case], "C")
    agg = report["aggregate"]
    assert agg["intentionally_skipped_local_call_count"] == 1
    assert agg["expected_local_call_missing_count"] == 0
    assert report["results"][0]["local_call_status"] == "intentionally_skipped"
    # An intentional skip is not an integrity failure.
    assert report["hard_thresholds_passed"] is True


def test_expected_local_call_missing_when_required_but_absent(monkeypatch):
    from aivan.telemetry.benchmark import BenchmarkCase

    _patch_no_llm_structuring(monkeypatch)
    case = BenchmarkCase(case_id="needs_model", tier="simple", input_language="en",
                         raw_text="5000 pcs to Osaka in 45 days", llm_required=True)
    report = benchmark.run_benchmark([case], "C")
    assert report["aggregate"]["expected_local_call_missing_count"] == 1
    assert report["results"][0]["local_call_status"] == "expected_local_call_missing"
    assert report["hard_thresholds_passed"] is False
    assert any("expected_local_call_missing" in f for f in report["hard_threshold_failures"])


def test_benchmark_reports_local_llm_tokens_latency_and_task(monkeypatch, _cases):
    monkeypatch.setattr(OllamaProvider, "complete_json", lambda self, *a, **k: dict(_CANNED))
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    report = benchmark.run_benchmark(_cases, "C")
    agg = report["aggregate"]
    assert agg["local_llm_tokens"] > 0
    assert agg["local_llm_latency_ms"] >= 0
    assert "requirement_structuring" in agg["local_llm_tasks"]
