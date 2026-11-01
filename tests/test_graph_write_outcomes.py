"""Synthetic consumer recovery, not real-provider deduplication or DB acceptance."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json

import httpx
import pytest

from aivan.integrations.giraffe_db import persist_rfq_gltg_graph
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import FallbackTrigger, GLTGSimulation, RFQStrategy

TENANT = "tenant-graph-recovery"
TRACE = "aivan:proj-recovery:msg-recovery"
OPERATIONS = [
    ("buyer", "/api/data/buyers", "buyer_id", "b1"),
    ("procurement-case", "/api/data/procurement-cases", "procurement_case_id", "pc1"),
    ("rfq", "/api/data/rfqs", "id", "rfq1"),
    ("gltg-run", "/api/data/gltg-simulation-runs", "gltg_run_id", "g1"),
    ("pricing-input", "/api/data/pricing-decision-inputs", "pricing_input_id", "pi1"),
    ("decision-option", "/api/data/case-decision-options", "decision_option_id", "do1"),
    ("comparison-snapshot", "/api/data/quote-comparison-snapshots", "comparison_snapshot_id", "cs1"),
]


@pytest.fixture
def graph_provider(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_PERSIST_GIRAFFE_DB_GRAPH", "true")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://graph-recovery.synthetic.test")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "synthetic-unit-credential")
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", raising=False)
    original_client = httpx.Client

    def configure(*, fail_index=None, status=202, success_status=201, readback_complete=True):
        calls = []
        stored = {}
        failed_once = False

        def handle(request):
            nonlocal failed_once
            assert request.headers["X-Service-Tenant-ID"] == TENANT
            assert request.headers["X-Service-Auth"] == "synthetic-unit-credential"
            key = request.headers.get("Idempotency-Key")
            calls.append((request.method, request.url.path, key))
            if request.method == "GET":
                assert request.url.path == "/api/data/procurement-cases/pc1/transaction-graph"
                assert len(stored) == len(OPERATIONS)
                records = [stored[(TENANT, f"{TRACE}:{step}")] for step, _, _, _ in OPERATIONS]
                graph = {
                    "procurement_case": deepcopy(records[1]),
                    **{section: [deepcopy(record)] for section, record in zip(
                        ["rfqs", "gltg_runs", "pricing_inputs", "decision_options", "comparison_snapshots"],
                        records[2:], strict=True,
                    )},
                }
                if not readback_complete:
                    graph["comparison_snapshots"] = []
                return httpx.Response(200, json=graph)

            assert request.method == "POST"
            index = next(i for i, op in enumerate(OPERATIONS) if op[1] == request.url.path)
            step, _, identity, value = OPERATIONS[index]
            payload = json.loads(request.content)
            assert key == payload["idempotency_key"] == f"{TRACE}:{step}"
            assert payload["source_trace_id"] == TRACE
            assert payload["source_event_id"] == "msg-recovery"
            if index == 0:
                assert payload["metadata_json"]["aivan_sender_id"] == "buyer-recovery"
            failing = index == fail_index and not failed_once
            if failing:
                failed_once = True
                if 400 <= status < 500:
                    return httpx.Response(status, json={"detail": "synthetic rejection"})
            storage_key = (TENANT, key)
            if storage_key in stored:
                # This synthetic provider explicitly supports replay. It is not
                # evidence that a deployed provider implements deduplication.
                assert stored[storage_key] == {**payload, identity: value, "tenant_id": TENANT}
            else:
                stored[storage_key] = {**payload, identity: value, "tenant_id": TENANT}
            # Simulate the ambiguous case: the provider may have saved this
            # operation even though its response does not confirm completion.
            return httpx.Response(status if failing else success_status, json=stored[storage_key])

        class Client(original_client):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, transport=httpx.MockTransport(handle))

        monkeypatch.setattr(httpx, "Client", Client)

        def invoke():
            return persist_rfq_gltg_graph(
                event=OpenClawEvent(
                    source="openclaw", channel="wechat", conversation_id="conv-recovery",
                    message_id="msg-recovery", sender_id="buyer-recovery", message_text="RFQ",
                    tenant_id=TENANT,
                ),
                project_id="proj-recovery",
                requirement=BuyerRequirement(quantity=100, destination="Osaka"),
                strategy=RFQStrategy(),
                gltg=GLTGSimulation(
                    p50_days=0.5, p80_days=7.5, p90_days=29.25, minimum_feasible_days=0.25,
                    supplier_set_feasibility="sufficient", known_suppliers_first_feasibility="feasible",
                    public_bidding_time_cost_days=5,
                    fallback_trigger_recommendation=FallbackTrigger(), selected_confidence_days=7.5,
                ),
            )

        return calls, stored, invoke

    return configure


@pytest.mark.parametrize("status", [202, 206])
@pytest.mark.parametrize("fail_index", range(len(OPERATIONS)), ids=[op[0] for op in OPERATIONS])
def test_nonfinal_write_stops_then_same_key_retry_verifies_readback(graph_provider, status, fail_index):
    calls, stored, invoke = graph_provider(fail_index=fail_index, status=status)
    step = OPERATIONS[fail_index][0]
    with pytest.raises(RuntimeError, match=f"^GIRAFFE_DB_GRAPH_INDETERMINATE_COMMIT:{step}$"):
        invoke()
    first_attempt = [("POST", path, f"{TRACE}:{op}") for op, path, _, _ in OPERATIONS[:fail_index + 1]]
    assert calls == first_attempt  # No dependent write or readback after the unknown outcome.
    assert len(stored) == fail_index + 1  # Not a zero-write or rollback claim.
    previous_records = deepcopy(stored)

    result = invoke()
    assert calls[len(first_attempt):] == [
        ("POST", path, f"{TRACE}:{op}") for op, path, _, _ in OPERATIONS
    ] + [("GET", "/api/data/procurement-cases/pc1/transaction-graph", None)]
    assert result["tenant_id"] == TENANT
    assert result["idempotency_key"] == TRACE
    assert result["readback_verified"] is True
    assert len(stored) == len(OPERATIONS)
    assert all(stored[key] == value for key, value in previous_records.items())
    counts = Counter(key for method, _, key in calls if method == "POST")
    assert counts == Counter({f"{TRACE}:{op}": 2 if i <= fail_index else 1
                              for i, (op, _, _, _) in enumerate(OPERATIONS)})
    assert stored[(TENANT, f"{TRACE}:rfq")]["status"] == "draft_pending_approval"
    assert stored[(TENANT, f"{TRACE}:pricing-input")]["manual_review_required"] is True
    decision = stored[(TENANT, f"{TRACE}:decision-option")]
    assert decision["status"] == "draft"
    assert decision["recommendation_reason_json"]["human_approval_required"] is True


@pytest.mark.parametrize("status", [202, 206])
def test_retry_does_not_report_recovery_without_readback(graph_provider, status):
    calls, _, invoke = graph_provider(fail_index=6, status=status, readback_complete=False)
    with pytest.raises(RuntimeError, match="^GIRAFFE_DB_GRAPH_INDETERMINATE_COMMIT:comparison-snapshot$"):
        invoke()
    assert len(calls) == 7
    with pytest.raises(RuntimeError, match="^GIRAFFE_DB_GRAPH_READBACK_MISMATCH:comparison_snapshots$"):
        invoke()
    assert [method for method, _, _ in calls] == ["POST"] * 14 + ["GET"]


@pytest.mark.parametrize("status", [200, 201])
def test_final_write_acknowledgements_remain_compatible(graph_provider, status):
    calls, _, invoke = graph_provider(success_status=status)
    assert invoke()["readback_verified"] is True
    assert [method for method, _, _ in calls] == ["POST"] * 7 + ["GET"]


@pytest.mark.parametrize("status", [401, 403, 409, 422])
def test_explicit_write_rejections_remain_http_errors(graph_provider, status):
    calls, stored, invoke = graph_provider(fail_index=0, status=status)
    with pytest.raises(httpx.HTTPStatusError) as error:
        invoke()
    assert error.value.response.status_code == status
    assert calls == [("POST", OPERATIONS[0][1], f"{TRACE}:buyer")]
    assert stored == {}
