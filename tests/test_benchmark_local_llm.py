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


def test_benchmark_reports_local_llm_tokens_latency_and_task(monkeypatch, _cases):
    monkeypatch.setattr(OllamaProvider, "complete_json", lambda self, *a, **k: dict(_CANNED))
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    report = benchmark.run_benchmark(_cases, "C")
    agg = report["aggregate"]
    assert agg["local_llm_tokens"] > 0
    assert agg["local_llm_latency_ms"] >= 0
    assert "requirement_structuring" in agg["local_llm_tasks"]
