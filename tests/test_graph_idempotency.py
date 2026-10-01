"""Giraffe DB graph trace + idempotency metadata tests (PRD §14, §18.9)."""
from __future__ import annotations

import httpx
import pytest

from aivan.integrations import giraffe_db
from aivan.integrations.giraffe_db import build_graph_trace_metadata, persist_rfq_gltg_graph
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy


def _event() -> OpenClawEvent:
    return OpenClawEvent(
        source="openclaw", channel="wechat", conversation_id="conv_graph_001",
        message_id="msg_graph_001", sender_id="buyer_1", message_text="RFQ",
    )


def _gltg() -> GLTGSimulation:
    return GLTGSimulation(
        p50_days=30.25, p80_days=38.5, p90_days=45.75, minimum_feasible_days=25.125,
        supplier_set_feasibility="sufficient", known_suppliers_first_feasibility="feasible",
        public_bidding_time_cost_days=5, fallback_trigger_recommendation=FallbackTrigger(),
        selected_confidence_days=38.5,
    )


def test_graph_trace_metadata_is_deterministic():
    event = _event()
    a = build_graph_trace_metadata(event, "proj_1")
    b = build_graph_trace_metadata(event, "proj_1")
    assert a == b
    assert a["source_trace_id"] == "aivan:proj_1:msg_graph_001"
    assert a["idempotency_key"] == a["source_trace_id"]
    assert a["source_system"] == "aivan"


def test_graph_payloads_include_trace_metadata_and_idempotency_header(monkeypatch):
    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "true")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")

    captured_payloads: list[dict] = []
    captured_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        if request.method == "GET":
            lineage = {"source_trace_id": "aivan:proj_1:msg_graph_001"}
            return httpx.Response(200, json={
                "procurement_case": {"procurement_case_id": "pc1", "metadata_json": lineage},
                "rfqs": [{"id": "rfq1", "metadata_json": lineage}],
                "gltg_runs": [{"gltg_run_id": "g1", "explanation_json": lineage}],
                "pricing_inputs": [{"pricing_input_id": "pi1", "explanation_json": lineage}],
                "decision_options": [{"decision_option_id": "do1", "metadata_json": lineage}],
                "comparison_snapshots": [{"comparison_snapshot_id": "cs1", "metadata_json": lineage}],
            })
        captured_payloads.append(_json.loads(request.content))
        captured_headers.append(dict(request.headers))
        return httpx.Response(200, json={
            "buyer_id": "b1", "procurement_case_id": "pc1", "id": "rfq1",
            "gltg_run_id": "g1", "pricing_input_id": "pi1", "decision_option_id": "do1",
            "comparison_snapshot_id": "cs1",
        })

    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    # giraffe_db imports httpx inside the function, so patching httpx.Client works.
    monkeypatch.setattr(httpx, "Client", _PatchedClient)

    result = persist_rfq_gltg_graph(
        event=_event(), project_id="proj_1",
        requirement=BuyerRequirement(quantity=5000, destination="Osaka"),
        strategy=RFQStrategy(), gltg=_gltg(),
    )

    assert result["source_trace_id"] == "aivan:proj_1:msg_graph_001"
    assert result["idempotency_key"] == "aivan:proj_1:msg_graph_001"
    assert captured_payloads, "expected at least one POST"
    for payload in captured_payloads:
        assert payload["source_system"] == "aivan"
        assert payload["source_trace_id"] == "aivan:proj_1:msg_graph_001"
        assert payload["idempotency_key"].startswith("aivan:proj_1:msg_graph_001:")
    assert len({payload["idempotency_key"] for payload in captured_payloads}) == len(captured_payloads)
    for payload in captured_payloads[1:]:
        lineage_container = payload.get("metadata_json") or payload.get("explanation_json")
        assert lineage_container["source_trace_id"] == "aivan:proj_1:msg_graph_001"
    for headers in captured_headers:
        assert headers.get("idempotency-key", "").startswith("aivan:proj_1:msg_graph_001:")
    assert len({headers["idempotency-key"] for headers in captured_headers}) == len(captured_headers)

    gltg_payload = next(payload for payload in captured_payloads if "final_p50_days" in payload)
    assert gltg_payload["final_p50_days"] == 30.25
    assert gltg_payload["final_p80_days"] == 38.5
    assert gltg_payload["final_p90_days"] == 45.75

    decision_payload = next(payload for payload in captured_payloads if "decision_option_id" not in payload and "option_label" in payload)
    assert decision_payload["p50_days"] == 30.25
    assert decision_payload["p80_days"] == 38.5
    assert decision_payload["p90_days"] == 45.75
    assert "estimated_lead_time_days" not in decision_payload


def test_enabled_graph_persistence_requires_giraffe_db_endpoint(monkeypatch):
    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "true")
    monkeypatch.delenv("GIRAFFE_DB_BASE_URL", raising=False)

    with pytest.raises(
        RuntimeError,
        match="GIRAFFE_DB_BASE_URL_REQUIRED_FOR_GRAPH_PERSISTENCE",
    ):
        persist_rfq_gltg_graph(
            event=_event(),
            project_id="proj_missing_endpoint",
            requirement=BuyerRequirement(quantity=5000, destination="Osaka"),
            strategy=RFQStrategy(),
            gltg=_gltg(),
        )


def test_production_refuses_to_bypass_authoritative_graph_persistence(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "false")

    with pytest.raises(RuntimeError, match="GIRAFFE_DB_GRAPH_PERSISTENCE_REQUIRED"):
        persist_rfq_gltg_graph(
            event=_event(),
            project_id="proj_production",
            requirement=BuyerRequirement(quantity=5000, destination="Osaka"),
            strategy=RFQStrategy(),
            gltg=_gltg(),
        )


def test_graph_retry_uses_same_idempotency_key(monkeypatch):
    a = build_graph_trace_metadata(_event(), "proj_retry")
    b = build_graph_trace_metadata(_event(), "proj_retry")
    assert a["idempotency_key"] == b["idempotency_key"]
