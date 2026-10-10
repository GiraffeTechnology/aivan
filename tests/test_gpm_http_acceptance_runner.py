"""Evidence-boundary tests for the real GPM/giraffe-db HTTP runner."""

from __future__ import annotations

import json

import pytest

from scripts.run_gpm_giraffe_db_http_acceptance import (
    AcceptanceFailure,
    Settings,
    _assert_packet,
    _result_status,
)


def _settings() -> Settings:
    return Settings(
        gpm_url="http://127.0.0.1:8080",
        db_url="http://127.0.0.1:8088",
        tenant_id="tenant-acceptance",
        actor_id="aivan-service",
        actor_role="orchestrator",
        gpm_api_key="not-logged",
        db_service_auth="not-logged",
        idempotency_key="acceptance-key",
        trace_id="acceptance-trace",
        cross_tenant_id=None,
        cross_tenant_api_key=None,
    )


def _packet(*, runtime_status: str, provider: str | None) -> dict:
    deterministic = runtime_status == "disabled" and provider == "none"
    quote_position = "insufficient_data" if deterministic else "within_mid_range"
    confidence = "low" if deterministic else "medium"
    model_result = {
        "recommendation": "human_review_required",
        "quote_position": quote_position,
        "confidence": confidence,
        "human_approval_required": True,
        "runtime_status": runtime_status,
        "model_provider": provider,
        "model_name": None if provider in {"mock", "none"} else "identified-model",
    }
    if deterministic:
        model_result["calculation"] = {
            "supplied_supplier_total": 1250.0,
            "supplied_buyer_total": 1500.0,
            "quoted_total_difference": 250.0,
            "quoted_total_difference_rate": 0.17,
        }
    return {
        "packet_id": "gpm_pkt_acceptance001",
        "tenant_id": "tenant-acceptance",
        "actor_id": "aivan-service",
        "actor_role": "orchestrator",
        "human_approval_required": True,
        "approval_status": "pending",
        "dispatched": False,
        "recommendation": "human_review_required",
        "quote_position": quote_position,
        "confidence": confidence,
        "supplier_total": 1250.0,
        "buyer_total": 1500.0,
        "model_result": model_result,
        "lineage": {"source_trace_id": "acceptance-trace"},
        "llm_reasoning": json.dumps({"runtime_status": runtime_status}),
    }


def test_actual_mode_rejects_mock_provider_identity() -> None:
    with pytest.raises(AcceptanceFailure, match="identified live model"):
        _assert_packet(_packet(runtime_status="mock", provider="mock"), _settings())


def test_actual_mode_rejects_deterministic_model_disabled_identity() -> None:
    with pytest.raises(AcceptanceFailure, match="identified live model"):
        _assert_packet(
            _packet(runtime_status="disabled", provider="none"),
            _settings(),
        )


def test_mock_mode_accepts_only_explicit_mock_evidence() -> None:
    packet_id = _assert_packet(
        _packet(runtime_status="mock", provider="mock"),
        _settings(),
        model_mode="mock",
    )
    assert packet_id == "gpm_pkt_acceptance001"


def test_mock_mode_rejects_actual_provider_evidence() -> None:
    with pytest.raises(AcceptanceFailure, match="declared mock"):
        _assert_packet(
            _packet(runtime_status="available", provider="qwen"),
            _settings(),
            model_mode="mock",
        )


def test_mock_mode_rejects_deterministic_provider_evidence() -> None:
    with pytest.raises(AcceptanceFailure, match="declared mock"):
        _assert_packet(
            _packet(runtime_status="disabled", provider="none"),
            _settings(),
            model_mode="mock",
        )


def test_deterministic_mode_accepts_only_explicit_model_disabled_evidence() -> None:
    packet_id = _assert_packet(
        _packet(runtime_status="disabled", provider="none"),
        _settings(),
        model_mode="deterministic",
    )
    assert packet_id == "gpm_pkt_acceptance001"


@pytest.mark.parametrize(
    ("runtime_status", "provider"),
    [("mock", "mock"), ("available", "qwen"), ("disabled", "qwen")],
)
def test_deterministic_mode_rejects_mock_live_or_named_provider_evidence(
    runtime_status: str, provider: str,
) -> None:
    with pytest.raises(AcceptanceFailure, match="deterministic model-disabled"):
        _assert_packet(
            _packet(runtime_status=runtime_status, provider=provider),
            _settings(),
            model_mode="deterministic",
        )


def test_deterministic_mode_rejects_a_model_name() -> None:
    packet = _packet(runtime_status="disabled", provider="none")
    packet["model_result"]["model_name"] = "unexpected-model"
    with pytest.raises(AcceptanceFailure, match="deterministic model-disabled"):
        _assert_packet(packet, _settings(), model_mode="deterministic")


def test_result_status_distinguishes_all_three_modes() -> None:
    assert _result_status("actual") == "PASS"
    assert _result_status("deterministic") == "PASS_DETERMINISTIC_MODEL_DISABLED"
    assert _result_status("mock") == "PASS_PERSISTENCE_ONLY_MODEL_MOCK"
