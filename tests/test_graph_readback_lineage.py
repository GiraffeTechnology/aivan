"""Synthetic transport regression: identity and lineage belong to one record.

This tests the Aivan consumer, not a real provider or CTYun/MySQL acceptance.
"""
from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from aivan.integrations.giraffe_db import persist_rfq_gltg_graph
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy

TRACE = "aivan:proj-readback:msg-readback"
SECTIONS = [
    ("rfqs", "id", "rfq1", "metadata_json"),
    ("gltg_runs", "gltg_run_id", "g1", "explanation_json"),
    ("pricing_inputs", "pricing_input_id", "pi1", "explanation_json"),
    ("decision_options", "decision_option_id", "do1", "metadata_json"),
    ("comparison_snapshots", "comparison_snapshot_id", "cs1", "metadata_json"),
]


def _graph():
    return {
        "procurement_case": {
            "procurement_case_id": "pc1", "metadata_json": {"source_trace_id": TRACE},
        },
        **{
            section: [{identity: value, lineage: {"source_trace_id": TRACE}}]
            for section, identity, value, lineage in SECTIONS
        },
    }


@pytest.fixture
def invoke_graph(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "true")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://graph.synthetic.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "synthetic-unit-credential")
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raising=False)
    graph = _graph()
    calls = []

    def handle(request):
        assert request.headers["X-Service-Tenant-ID"] == "tenant-graph-unit"
        assert request.headers["X-Service-Auth"] == "synthetic-unit-credential"
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=graph)
        return httpx.Response(201, json={
            "buyer_id": "b1", "procurement_case_id": "pc1", "id": "rfq1",
            "gltg_run_id": "g1", "pricing_input_id": "pi1", "decision_option_id": "do1",
            "comparison_snapshot_id": "cs1",
        })

    original = httpx.Client

    class Client(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "Client", Client)

    def invoke():
        return persist_rfq_gltg_graph(
            event=OpenClawEvent(
                source="openclaw", channel="wechat", conversation_id="conv-readback",
                message_id="msg-readback", sender_id="buyer-unit", message_text="RFQ",
                tenant_id="tenant-graph-unit",
            ),
            project_id="proj-readback",
            requirement=BuyerRequirement(quantity=100, destination="Osaka"),
            strategy=RFQStrategy(),
            gltg=GLTGSimulation(
                p50_days=0.5, p80_days=7.5, p90_days=29.25, minimum_feasible_days=0.25,
                supplier_set_feasibility="sufficient", known_suppliers_first_feasibility="feasible",
                public_bidding_time_cost_days=5,
                fallback_trigger_recommendation=FallbackTrigger(), selected_confidence_days=7.5,
            ),
        )

    return graph, calls, invoke


@pytest.mark.parametrize("section,identity,value,lineage", SECTIONS)
@pytest.mark.parametrize("decoy_first", [False, True])
@pytest.mark.parametrize("wrong_trace", [None, "aivan:other-project:other-message"])
def test_readback_rejects_lineage_from_a_different_record(
    invoke_graph, section, identity, value, lineage, decoy_first, wrong_trace,
):
    graph, calls, invoke = invoke_graph
    target = graph[section][0]
    decoy = deepcopy(target)
    decoy[identity] = value + "-unrelated"
    target[lineage]["source_trace_id"] = wrong_trace
    graph[section] = [decoy, target] if decoy_first else [target, decoy]

    with pytest.raises(RuntimeError, match=f"GIRAFFE_DB_GRAPH_READBACK_LINEAGE_MISMATCH:{section}"):
        invoke()
    assert len([method for method, _ in calls if method == "POST"]) == 7
    assert calls[-1] == ("GET", "/api/data/procurement-cases/pc1/transaction-graph")


@pytest.mark.parametrize("section,identity,value,lineage", SECTIONS)
@pytest.mark.parametrize("decoy_first", [False, True])
def test_readback_allows_unrelated_historical_rows(
    invoke_graph, section, identity, value, lineage, decoy_first,
):
    graph, _, invoke = invoke_graph
    target = graph[section][0]
    historical = deepcopy(target)
    historical[identity] = value + "-historical"
    historical[lineage]["source_trace_id"] = "aivan:historical:message"
    graph[section] = [historical, target] if decoy_first else [target, historical]
    assert invoke()["readback_verified"] is True
