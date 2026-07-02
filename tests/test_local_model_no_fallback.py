"""P0-2: no silent fallback from a local/external provider to mock (PR #29)."""
from __future__ import annotations

import pytest

from aivan.llm import gateway
from aivan.llm.gateway import llm_complete_json
from aivan.llm.policy import LocalModelUnavailableError
from aivan.llm.providers.ollama_provider import OllamaProvider
from aivan.rfq.dependency_policy import classify_exception
from aivan.telemetry import benchmark


@pytest.fixture(autouse=True)
def _reset_provider():
    gateway.reset_provider()
    yield
    gateway.reset_provider()


def test_ollama_failure_does_not_fallback_to_mock(monkeypatch):
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "true")

    def _boom(self, *a, **k):
        raise ConnectionError("ollama refused")

    monkeypatch.setattr(OllamaProvider, "complete_json", _boom)
    gateway.reset_provider()

    with pytest.raises(LocalModelUnavailableError):
        llm_complete_json("requirement_structuring", "sys", "user", {})


def test_mock_provider_only_when_explicitly_configured(monkeypatch):
    # Explicit mock provider works.
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "mock")
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "true")
    gateway.reset_provider()
    result = llm_complete_json("requirement_structuring", "sys", "user", {})
    assert isinstance(result, dict) and result  # mock returns canned structure

    # A failing ollama must NOT be rescued by the mock provider's canned answer.
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(OllamaProvider, "complete_json", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    gateway.reset_provider()
    with pytest.raises(LocalModelUnavailableError):
        llm_complete_json("requirement_structuring", "sys", "user", {})


def test_local_model_unavailable_records_recovery_state():
    recovery = classify_exception(LocalModelUnavailableError("ollama"))
    assert recovery.dependency == "local_model"
    assert recovery.action == "reduced_strength_local_model_unavailable"
    assert recovery.manual_review_required is True
    # Reduced-strength message must state no cloud fallback happened.
    assert "cloud" in recovery.operator_message_en.lower()


def test_mode_c_benchmark_fails_if_ollama_not_called(monkeypatch):
    # Ollama unavailable -> structuring raises, benchmark must FAIL mode C rather
    # than let a dead local model look like success.
    def _boom(self, *a, **k):
        raise ConnectionError("ollama refused")

    monkeypatch.setattr(OllamaProvider, "complete_json", _boom)
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")

    cases = benchmark.load_cases(benchmark.default_cases_path())[:3]
    report = benchmark.run_benchmark(cases, "C")
    assert report["hard_thresholds_passed"] is False
    assert any("ollama_not_called" in f for f in report["hard_threshold_failures"])
    assert report["aggregate"]["real_local_call_count"] == 0
