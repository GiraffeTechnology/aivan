"""Evidence-boundary tests for the real GPM/giraffe-db HTTP runner."""

from __future__ import annotations

import json

import pytest

from scripts.run_gpm_giraffe_db_http_acceptance import (
    AcceptanceFailure,
    Settings,
    _assert_packet,
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
    model_result = {
        "recommendation": "human_review_required",
        "confidence": "medium",
        "runtime_status": runtime_status,
        "model_provider": provider,
        "model_name": None if provider == "mock" else "identified-model",
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
        "quote_position": "within_mid_range",
        "confidence": "medium",
        "model_result": model_result,
        "lineage": {"source_trace_id": "acceptance-trace"},
        "llm_reasoning": json.dumps({"runtime_status": runtime_status}),
    }


def test_actual_mode_rejects_mock_provider_identity() -> None:
    with pytest.raises(AcceptanceFailure, match="identified live model"):
        _assert_packet(_packet(runtime_status="mock", provider="mock"), _settings())


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
