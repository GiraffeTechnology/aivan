from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.db.models import Base
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.integrations.giraffe_db import GiraffeDBClient
from aivan.integrations.gltg import GLTGClient
from aivan.execution.rfq_execution import interpret_strategy
from aivan.openclaw.outbound_approval import send_if_approved
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import RFQStrategy


@pytest.fixture(autouse=True)
def _language_skill_resolves_canonical_fields(monkeypatch):
    """These integration tests assume the language skill is available.

    Under the private-domain provenance model a local-LLM-only extraction is
    provisional and blocks on confirmation; these end-to-end tests exercise the
    *executed* path, so they simulate the language skill having resolved
    canonical product/destination (marking those fields authoritative).
    """
    import aivan.execution.rfq_execution as rfqe
    from aivan.agents import requirement_agent

    real = rfqe.structure_customer_requirement_with_llm

    def canonicalize(raw_text: str, **kwargs):
        if "白色纯棉衬衣" not in raw_text and "温哥华" not in raw_text:
            return None
        return {
            "normalize": {
                "raw_text": raw_text,
                "language": {"detected": "zh", "confidence": 0.99},
                "canonical_language": "en",
                "canonical_text": (
                    "Urgent RFQ: 10000 pcs high quality white cotton shirts, "
                    "deliver to Vancouver within 45 days; ask familiar suppliers first."
                ),
                "requested_output_language": "zh",
                "field_evidence": {
                    "quantity": {"raw": "10000 件", "value": 10000},
                    "product_name": {"raw": "白色纯棉衬衣", "value": "white cotton shirt"},
                    "destination": {"raw": "温哥华", "value": "Vancouver"},
                    "lead_time_days": {"raw": "45 天", "value": 45},
                },
            },
            "structure": {
                "schema": "trade_rfq.v1",
                "validation_status": "valid",
                "structured": {
                    "quantity": 10000,
                    "quantity_unit": "pcs",
                    "product_name": "white cotton shirt",
                    "product_category": "apparel",
                    "destination": "Vancouver",
                    "lead_time_days": 45,
                    "quality_level": "high",
                    "intent": "supplier_rfq",
                },
                "missing_fields": [],
                "confidence_score": 0.95,
                "field_sources": {
                    "quantity": "language_skill",
                    "product_name": "language_skill",
                    "destination": "language_skill",
                    "lead_time_days": "language_skill",
                },
            },
        }

    def wrapped(**kwargs):
        req = real(**kwargs)
        sources = req.extra.setdefault("field_sources", {})
        if req.destination:
            sources["destination"] = "language_skill"
        if req.product_type:
            sources["product_type"] = "language_skill"
        return req

    monkeypatch.setattr(requirement_agent, "canonicalize_rfq", canonicalize)
    monkeypatch.setattr(rfqe, "structure_customer_requirement_with_llm", wrapped)
    yield


@pytest.fixture
def api_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()
    engine.dispose()


@pytest.fixture
def api_client(api_db):
    from aivan.api.main import app, get_db

    def override_db():
        yield api_db

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _user_rfq_event() -> dict:
    return {
        "source": "openclaw",
        "channel": "wechat",
        "conversation_id": "conv_user_rfq_001",
        "message_id": "msg_user_rfq_001",
        "sender_id": "user_001",
        "sender_display_name": "Michael",
        "message_text": "这个客户很急，先问熟悉供应商。帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华。",
        "role_context": "user",
        "mode": "command",
    }


def _customer_email_event() -> dict:
    return {
        "source": "openclaw",
        "channel": "email",
        "conversation_id": "email_thread_customer_001",
        "message_id": "email_msg_001",
        "sender_id": "customer_vancouver_001",
        "sender_display_name": "Vancouver Buyer",
        "actor_id": "user_001",
        "message_text": "We need 10,000 white 100% cotton shirts delivered to Vancouver within 45 days. Please advise.",
        "role_context": "customer",
        "mode": "auto",
    }


def _customer_personal_im_event_missing_actor() -> dict:
    return {
        "source": "openclaw",
        "channel": "wechat",
        "channel_account_id": "sales-user-wechat",
        "conversation_id": "customer_personal_im_thread_001",
        "message_id": "customer_im_msg_001",
        "sender_id": "customer_wechat_counterparty_001",
        "sender_display_name": "Vancouver Buyer WeChat",
        "message_text": "We need 10,000 white cotton shirts delivered to Vancouver within 45 days.",
        "role_context": "customer",
        "mode": "auto",
    }


def test_strategy_interpretation_urgent_known_supplier_command():
    strategy = interpret_strategy("这个客户很急，先找靠谱的老供应商，价格别太离谱。")

    assert strategy.priority == "speed"
    assert strategy.supplier_scope == "known_suppliers_first"
    assert strategy.public_bidding == "fallback_only"
    assert strategy.lead_time_confidence == "P80"
    assert strategy.price_sensitivity == "medium"
    assert strategy.quality_sensitivity == "high"
    assert strategy.fallback_trigger.min_valid_supplier_replies == 2
    assert strategy.fallback_trigger.max_wait_hours == 24


def test_create_rfq_from_user_command_creates_pending_email_drafts(api_client):
    response = api_client.post("/api/rfq/create-from-event", json=_user_rfq_event())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["event_type"] == "user_command"
    assert payload["action"] == "pending_email_approval"
    assert payload["strategy"]["priority"] == "speed"
    assert payload["gltg_simulation"]["p80_days"] > 0
    assert payload["drafts_created"]
    # The user command is Chinese, so the operator summary is rendered in Chinese.
    user_control_message = payload["user_control_message"]
    assert (
        "pending approval" in user_control_message.lower()
        or "等待人工审批" in user_control_message
        or "仍需人工审批" in user_control_message
    )

    drafts = api_client.get(f"/api/projects/{payload['project_id']}/drafts").json()["drafts"]
    supplier_drafts = [draft for draft in drafts if draft["target_role"] == "supplier"]
    user_notifications = [draft for draft in drafts if draft["target_role"] == "user"]
    assert supplier_drafts
    assert user_notifications
    assert {draft["channel"] for draft in supplier_drafts} == {"email"}
    assert {draft["status"] for draft in supplier_drafts} == {"pending_approval"}
    assert {draft["draft_type"] for draft in supplier_drafts} == {"supplier_inquiry_email"}
    assert user_notifications[0]["draft_type"] == "approval_request_im"
    assert user_notifications[0]["status"] == "sent"


def test_chinese_user_control_message_is_localized_and_pending_approval():
    import types

    from aivan.execution.rfq_execution import _build_user_control_message
    from aivan.schemas.rfq import RFQStrategy, SupplierRoutingDecision

    requirement = BuyerRequirement(
        project_id="p1",
        raw_text="帮我询价 10000 件白色纯棉衬衣，45 天内交东京，高品质。",
        language="zh",
        product_type="shirt",
        quantity=10000,
        destination="Tokyo",
        delivery_days=45,
    )
    strategy = RFQStrategy(priority="speed", supplier_scope="known_suppliers_first")
    gltg = types.SimpleNamespace(selected_confidence_days=40, deadline_risk_level="medium")
    routing = SupplierRoutingDecision(selected_supplier_ids=["sup_001", "sup_002"])

    message = _build_user_control_message(
        requirement, strategy, gltg, routing, ["draft_1", "draft_2"]
    )

    # Chinese operator summary must still signal that the outbound drafts are
    # blocked on human approval.
    assert "等待人工审批" in message or "仍需人工审批" in message
    assert "Tokyo" in message


def test_giraffe_db_graph_persist_failure_does_not_block_pending_drafts(api_client, api_db, monkeypatch):
    import aivan.execution.rfq_execution as rfq_execution

    def fail_persist(**kwargs):
        raise RuntimeError("giraffe-db unavailable")

    monkeypatch.setattr(rfq_execution, "persist_rfq_gltg_graph", fail_persist)

    response = api_client.post("/api/rfq/create-from-event", json=_user_rfq_event())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["action"] == "pending_email_approval"
    assert payload["drafts_created"]

    drafts = api_client.get(f"/api/projects/{payload['project_id']}/drafts").json()["drafts"]
    supplier_drafts = [draft for draft in drafts if draft["target_role"] == "supplier"]
    assert supplier_drafts
    assert {draft["status"] for draft in supplier_drafts} == {"pending_approval"}

    from aivan.db.repositories.event_repo import ExecutionEventRepository

    events = ExecutionEventRepository(api_db).list_for_project(payload["project_id"])
    failure_events = [event for event in events if event.event_type == "GIRAFFE_DB_GRAPH_PERSIST_FAILED"]
    assert failure_events
    assert failure_events[0].payload_json["error_type"] == "RuntimeError"


def test_openclaw_events_uses_same_rfq_chain(api_client):
    response = api_client.post("/api/openclaw/events", json=_user_rfq_event())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_id"]
    assert payload["drafts_created"]
    assert payload["supplier_routing"]["selected_supplier_ids"]


def test_project_strategy_update_endpoint(api_client):
    created = api_client.post("/api/rfq/create-from-event", json=_user_rfq_event()).json()
    response = api_client.post(
        f"/api/projects/{created['project_id']}/strategy",
        json={
            "priority": "price",
            "supplier_scope": "known_suppliers_only",
            "public_bidding": "disabled",
            "lead_time_confidence": "P90",
            "price_sensitivity": "high",
            "quality_sensitivity": "medium",
            "fallback_trigger": {
                "min_valid_supplier_replies": 3,
                "max_wait_hours": 48,
                "lead_time_risk_threshold": "high",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["strategy"]["priority"] == "price"
    project = api_client.get(f"/api/projects/{created['project_id']}").json()
    assert project["requirement"]["strategy"]["lead_time_confidence"] == "P90"


def test_run_gltg_endpoint_updates_project_simulation(api_client):
    created = api_client.post("/api/rfq/create-from-event", json=_user_rfq_event()).json()

    response = api_client.post(f"/api/projects/{created['project_id']}/run-gltg", json={})

    assert response.status_code == 200, response.text
    simulation = response.json()["gltg_simulation"]
    assert simulation["p50_days"] > 0
    assert simulation["p80_days"] >= simulation["p50_days"]
    assert simulation["p90_days"] >= simulation["p80_days"]


def test_user_preference_api_and_giraffe_context_loading(api_client, api_db):
    response = api_client.post(
        "/api/user-preferences/update",
        json={
            "user_id": "user_001",
            "preference_type": "supplier_strategy",
            "value": {
                "default_supplier_scope": "known_suppliers_first",
                "public_bidding": "fallback_only",
                "lead_time_confidence": "P80",
            },
            "source": "approval_history",
            "confidence": 0.78,
        },
    )
    assert response.status_code == 200, response.text

    listed = api_client.get("/api/user-preferences?user_id=user_001")
    assert listed.status_code == 200
    assert listed.json()["preferences"][0]["value"]["lead_time_confidence"] == "P80"

    context = GiraffeDBClient(api_db).build_context(
        BuyerRequirement(category="apparel", product_type="shirt", quantity=10000),
        user_id="user_001",
    )
    assert context.user_preferences
    assert context.user_preferences[0]["preference_type"] == "supplier_strategy"


def test_giraffe_db_query_integration_returns_private_domain_context(api_db):
    context = GiraffeDBClient(api_db).build_context(
        BuyerRequirement(category="apparel", product_type="shirt", quantity=10000),
        customer_id="customer_001",
        user_id="user_001",
    )

    assert context.customers[0]["customer_id"] == "customer_001"
    assert context.suppliers
    assert context.supplier_relationships
    assert context.historical_rfqs
    assert context.historical_quotations
    assert context.historical_lead_time_records
    assert context.product_categories


def test_gltg_call_integration_and_public_bidding_fallback_trigger():
    strategy = RFQStrategy(public_bidding="fallback_only", lead_time_confidence="P80")
    simulation = GLTGClient().simulate(
        BuyerRequirement(category="apparel", product_type="shirt", quantity=10000, destination="Vancouver", delivery_days=45),
        strategy,
        supplier_count=2,
    )

    assert simulation.p80_days > 0
    assert simulation.public_bidding_time_cost_days == 5
    assert simulation.fallback_trigger_recommendation.min_valid_supplier_replies == 2


def test_customer_email_ingestion_creates_user_im_approval_notification(api_client):
    response = api_client.post("/api/rfq/create-from-event", json=_customer_email_event())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["event_type"] == "customer_new_inquiry"
    drafts = api_client.get(f"/api/projects/{payload['project_id']}/drafts").json()["drafts"]
    user_notifications = [d for d in drafts if d["target_role"] == "user"]
    assert user_notifications
    assert user_notifications[0]["channel"] == "im"
    assert user_notifications[0]["target_peer_id"] == "user_001"
    assert user_notifications[0]["draft_type"] == "approval_request_im"
    assert user_notifications[0]["status"] == "sent"


def test_supplier_reply_invokes_quote_option_and_customer_email_draft_path(api_client):
    created = api_client.post("/api/rfq/create-from-event", json=_customer_email_event()).json()
    supplier_event = {
        "source": "openclaw",
        "channel": "wechat",
        "conversation_id": "supplier_reply_thread_001",
        "message_id": "supplier_reply_msg_001",
        "sender_id": "supplier_001",
        "sender_display_name": "Guangzhou Trendy Garment",
        "project_id": created["project_id"],
        "message_text": "We can quote USD 4.50/pc, MOQ 5000 pcs, daily capacity 500 pcs, lead time 35 days, FOB Guangzhou.",
        "role_context": "supplier",
        "mode": "auto",
    }

    response = api_client.post("/api/openclaw/events", json=supplier_event)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["event_type"] == "supplier_reply"
    assert payload["action"] == "buyer_options_ready"
    assert payload["drafts_created"]

    project = api_client.get(f"/api/projects/{created['project_id']}").json()
    assert project["requirement"]["supplier_replies"][0]["unit_price"] == 4.5
    assert project["requirement"]["lead_time_estimates"][0]["expected_days"] > 0
    assert project["requirement"]["buyer_options"]
    assert project["selected_option"]["quote"]["buyer_unit_price"] > 0

    drafts = api_client.get(f"/api/projects/{created['project_id']}/drafts").json()["drafts"]
    customer_drafts = [d for d in drafts if d["target_role"] == "customer" and d["draft_type"] == "customer_quote_email"]
    assert customer_drafts
    assert customer_drafts[0]["channel"] == "email"
    assert customer_drafts[0]["status"] == "pending_approval"

    events = api_client.get(f"/api/projects/{created['project_id']}/events").json()["events"]
    assert any(event["event_type"] == "SUPPLIER_REPLY_PARSED" for event in events)
    assert any(event["event_type"] == "BUYER_OPTIONS_GENERATED" for event in events)


def test_customer_personal_im_without_actor_requires_owner_resolution(api_client):
    event = _customer_personal_im_event_missing_actor()

    response = api_client.post("/api/rfq/create-from-event", json=event)

    assert response.status_code == 200, response.text
    payload = response.json()
    drafts = api_client.get(f"/api/projects/{payload['project_id']}/drafts").json()["drafts"]
    user_notifications = [d for d in drafts if d["target_role"] == "user"]
    assert user_notifications
    assert user_notifications[0]["channel"] == "internal"
    assert user_notifications[0]["target_peer_id"] == "owner_resolution_required"
    assert user_notifications[0]["target_peer_id"] != event["sender_id"]
    assert user_notifications[0]["status"] == "pending_approval"
    assert "owner_resolution_required" in user_notifications[0]["notes"]


def test_second_supplier_reply_accumulates_both_replies_in_buyer_options(api_client):
    """P1+P2: all prior replies are preserved; lead times are matched to suppliers."""
    created = api_client.post("/api/rfq/create-from-event", json=_customer_email_event()).json()
    project_id = created["project_id"]

    # First supplier: better price, moderate lead time
    resp_a = api_client.post("/api/openclaw/events", json={
        "source": "openclaw",
        "channel": "email",
        "conversation_id": "supplier_a_conv_001",
        "message_id": "supplier_a_msg_001",
        "sender_id": "supplier_a",
        "sender_display_name": "Guangzhou Best Price Garment",
        "project_id": project_id,
        "message_text": "Quote: USD 3.80/pc, MOQ 5000, daily capacity 500 pcs, lead time 40 days, FOB Guangzhou.",
        "role_context": "supplier",
        "mode": "auto",
    }).json()
    assert resp_a["action"] == "buyer_options_ready"

    proj_after_a = api_client.get(f"/api/projects/{project_id}").json()
    assert len(proj_after_a["requirement"]["supplier_replies"]) == 1
    # P2: selected_option must carry a real lead time after first reply
    selected_a = proj_after_a["selected_option"]
    assert selected_a is not None
    assert selected_a.get("lead_time_estimate") is not None, "lead_time_estimate must not be None (P2)"
    assert selected_a["lead_time_estimate"]["expected_days"] > 0

    # Second supplier: higher price, faster delivery
    resp_b = api_client.post("/api/openclaw/events", json={
        "source": "openclaw",
        "channel": "email",
        "conversation_id": "supplier_b_conv_001",
        "message_id": "supplier_b_msg_001",
        "sender_id": "supplier_b",
        "sender_display_name": "Shenzhen Fast Garment",
        "project_id": project_id,
        "message_text": "Quote: USD 5.20/pc, MOQ 3000, daily capacity 1000 pcs, lead time 25 days, FOB Shenzhen.",
        "role_context": "supplier",
        "mode": "auto",
    }).json()
    assert resp_b["action"] == "buyer_options_ready"

    proj = api_client.get(f"/api/projects/{project_id}").json()

    # P1: both replies must be accumulated, not just the latest
    replies = proj["requirement"]["supplier_replies"]
    assert len(replies) == 2, "Both supplier replies must be preserved"
    reply_supplier_ids = {r["supplier_id"] for r in replies}
    assert "supplier_a" in reply_supplier_ids
    assert "supplier_b" in reply_supplier_ids

    # P1: buyer_options must reflect both suppliers
    buyer_options = proj["requirement"]["buyer_options"]
    assert len(buyer_options) >= 2, "Buyer options must cover multiple suppliers"
    option_supplier_ids = {opt.get("supplier_id") for opt in buyer_options}
    assert "supplier_a" in option_supplier_ids, "Earlier cheaper supplier A must remain in buyer options"
    assert "supplier_b" in option_supplier_ids, "Faster supplier B must appear in buyer options"

    # P1: supplier A's lower price must not be displaced
    buyer_prices = [opt["quote"]["buyer_unit_price"] for opt in buyer_options if opt.get("quote")]
    assert any(p < 5.5 for p in buyer_prices), "Buyer options must include supplier A's lower-priced quote"

    # P2: selected_option must still carry a valid lead time after second reply
    selected = proj["selected_option"]
    assert selected is not None
    assert selected.get("lead_time_estimate") is not None, "selected_option lead_time_estimate must not be None (P2)"
    assert selected["lead_time_estimate"]["expected_days"] > 0

    # P2: customer email draft must show numeric lead times, not N/A
    drafts = api_client.get(f"/api/projects/{project_id}/drafts").json()["drafts"]
    customer_drafts = [
        d for d in drafts
        if d["target_role"] == "customer" and d["draft_type"] == "customer_quote_email"
    ]
    assert customer_drafts
    latest_text = customer_drafts[-1]["message_text"]
    assert "N/A days" not in latest_text, "Customer email draft must not contain N/A lead times"


def test_invalid_llm_json_falls_back_to_deterministic_strategy(monkeypatch):
    import aivan.execution.rfq_execution as rfq_execution

    monkeypatch.setattr(rfq_execution, "llm_complete_json", lambda *args, **kwargs: {"result": "not a strategy"})

    strategy = rfq_execution.interpret_strategy("这个客户很急，先找靠谱的老供应商，价格别太离谱。")

    assert strategy.priority == "speed"
    assert strategy.supplier_scope == "known_suppliers_first"


@pytest.mark.parametrize(
    "raw_strategy",
    [
        {"priority": "speed", "supplier_scope": "known_supplier_first"},
        {"priority": "speed", "public_bidding": "fallback"},
        {"priority": "speed", "lead_time_confidence": "p80"},
    ],
)
def test_invalid_llm_strategy_fields_fall_back_deterministically(monkeypatch, raw_strategy):
    import aivan.execution.rfq_execution as rfq_execution

    monkeypatch.setattr(rfq_execution, "llm_complete_json", lambda *args, **kwargs: raw_strategy)

    strategy = rfq_execution.interpret_strategy("这个客户很急，先找靠谱的老供应商，价格别太离谱。")

    assert strategy.priority == "speed"
    assert strategy.supplier_scope == "known_suppliers_first"
    assert strategy.public_bidding == "fallback_only"
    assert strategy.lead_time_confidence == "P80"


def test_partial_llm_strategy_payload_uses_schema_defaults(monkeypatch):
    import aivan.execution.rfq_execution as rfq_execution

    monkeypatch.setattr(rfq_execution, "llm_complete_json", lambda *args, **kwargs: {"priority": "speed"})

    strategy = rfq_execution.interpret_strategy("urgent order")

    assert strategy.priority == "speed"
    assert strategy.supplier_scope == "known_suppliers_first"
    assert strategy.public_bidding == "fallback_only"
    assert strategy.lead_time_confidence == "P80"


def test_missing_project_attachment_is_validated_against_db(api_client):
    event = _user_rfq_event()
    event["project_id"] = "proj_does_not_exist"

    response = api_client.post("/api/rfq/create-from-event", json=event)

    assert response.status_code == 200, response.text
    assert response.json()["project_id"] != "proj_does_not_exist"


def test_gltg_unavailable_raises_no_silent_fallback():
    """When GLTG is unreachable, AIVAN must surface the error, never fabricate one."""
    import httpx

    from aivan.integrations.gltg import GLTGClient as GLTGFacade, GLTGUnavailableError
    from aivan.integrations.gltg_client import GLTGClient as GLTGHttp

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    facade = GLTGFacade(http=GLTGHttp(base_url="http://gltg.test", transport=httpx.MockTransport(boom)))
    with pytest.raises(GLTGUnavailableError):
        facade.simulate(
            BuyerRequirement(category="apparel", product_type="shirt", quantity=10000, destination="Vancouver", delivery_days=45),
            RFQStrategy(lead_time_confidence="P80"),
            supplier_count=2,
        )


def test_qwen_provider_does_not_leak_api_key_in_errors(monkeypatch):
    from aivan.llm.providers.qwen_provider import QwenProvider

    monkeypatch.setenv("QWEN_API_KEY", "secret-qwen-key")
    monkeypatch.setattr("aivan.llm.providers.qwen_provider.httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network down")))

    provider = QwenProvider()
    with pytest.raises(RuntimeError) as exc:
        provider.complete_json("task", "system", "user", {})

    assert "secret-qwen-key" not in str(exc.value)


def test_counterparty_personal_im_draft_cannot_be_sent(api_db):
    repo = DraftRepository(api_db)
    draft = repo.create(
        "proj_policy_001",
        {
            "conversation_id": "conv_policy",
            "channel": "wechat",
            "target_peer_id": "supplier_wechat",
            "target_role": "supplier",
            "message_text": "Please quote this order.",
            "status": "pending_approval",
            "created_by_agent": "test",
        },
    )
    repo.approve(draft.draft_id)
    api_db.commit()

    result = send_if_approved(draft.draft_id, api_db)

    assert result.success is False
    assert "channel policy blocks" in (result.error or "")
    assert repo.get(draft.draft_id).status == "approved"


# ── P2 acceptance tests ───────────────────────────────────────────────────────


def test_stale_customer_quote_draft_superseded_after_new_supplier_reply(api_client):
    """P2.1: older customer quote drafts must be superseded — not approvable — after a
    newer supplier reply regenerates buyer options."""
    created = api_client.post("/api/rfq/create-from-event", json=_customer_email_event()).json()
    project_id = created["project_id"]

    _supplier_reply_event = lambda sid, price, lt: {
        "source": "openclaw", "channel": "email",
        "conversation_id": f"{sid}_conv", "message_id": f"{sid}_msg",
        "sender_id": sid, "sender_display_name": sid,
        "project_id": project_id,
        "message_text": f"Quote: USD {price}/pc, MOQ 5000, lead time {lt} days.",
        "role_context": "supplier", "mode": "auto",
    }

    # First supplier reply → creates first quote draft
    api_client.post("/api/openclaw/events", json=_supplier_reply_event("sup_x", 4.50, 35))
    drafts_after_first = api_client.get(f"/api/projects/{project_id}/drafts").json()["drafts"]
    first_quote_drafts = [
        d for d in drafts_after_first
        if d["target_role"] == "customer" and d["draft_type"] == "customer_quote_email"
    ]
    assert first_quote_drafts, "First supplier reply should create a customer quote draft"
    first_draft_id = first_quote_drafts[0]["draft_id"]
    assert first_quote_drafts[0]["status"] == "pending_approval"

    # Second supplier reply → should supersede the first quote draft
    api_client.post("/api/openclaw/events", json=_supplier_reply_event("sup_y", 3.90, 28))
    drafts_after_second = api_client.get(f"/api/projects/{project_id}/drafts").json()["drafts"]

    # The original draft must be superseded, not pending_approval any more
    first_draft_current = next(d for d in drafts_after_second if d["draft_id"] == first_draft_id)
    assert first_draft_current["status"] == "superseded", (
        "First customer quote draft must be superseded after second supplier reply"
    )

    # Attempting to approve the stale draft via the API must fail or return non-pending
    approve_resp = api_client.post(f"/api/projects/{project_id}/drafts/{first_draft_id}/approve")
    if approve_resp.status_code == 200:
        # API accepted, but status should not have transitioned to 'approved'
        assert approve_resp.json().get("status") != "approved", (
            "Superseded draft must not be approvable"
        )

    # A fresh pending quote draft must now exist
    fresh_pending = [
        d for d in drafts_after_second
        if d["target_role"] == "customer" and d["draft_type"] == "customer_quote_email"
        and d["status"] == "pending_approval"
    ]
    assert fresh_pending, "A new pending customer quote draft must exist after the second supplier reply"


def test_supplier_set_feasibility_not_thin_with_two_replies(api_client):
    """P2.2: GLTG supplier_set_feasibility must not be 'thin' once ≥2 valid supplier replies
    have been accumulated; supplier_count is passed as len(all_replies)."""
    created = api_client.post("/api/rfq/create-from-event", json=_customer_email_event()).json()
    project_id = created["project_id"]

    for sid, price, lt in [("sup_a", 4.50, 35), ("sup_b", 5.20, 25)]:
        resp = api_client.post("/api/openclaw/events", json={
            "source": "openclaw", "channel": "email",
            "conversation_id": f"{sid}_feasibility_conv", "message_id": f"{sid}_feasibility_msg",
            "sender_id": sid, "sender_display_name": sid,
            "project_id": project_id,
            "message_text": f"Quote: USD {price}/pc, MOQ 5000, lead time {lt} days.",
            "role_context": "supplier", "mode": "auto",
        }).json()
        assert resp["action"] == "buyer_options_ready"

    proj = api_client.get(f"/api/projects/{project_id}").json()
    assert len(proj["requirement"]["supplier_replies"]) == 2

    gltg = proj["requirement"].get("gltg_simulation") or proj.get("gltg_simulation")
    # After two replies the supplier_count passed to GLTG must be 2 → not thin
    if gltg:
        assert gltg.get("supplier_set_feasibility") != "thin", (
            "supplier_set_feasibility must not be 'thin' when 2 valid replies are present"
        )


def test_owner_resolution_ignores_revoked_account_prefers_active(api_client, api_db):
    """P2.3: _owner_user_id_for_event must resolve only the active/connected account
    and ignore a stale/revoked account that shares the same channel_account_id."""
    from aivan.db.models.account import OpenClawAccountRecord

    channel = "wechat"
    shared_channel_account_id = "shared-wechat-account"

    # Stale/revoked account — same channel_account_id but status != "connected"
    revoked = OpenClawAccountRecord(
        account_connection_id="revoked-acct-001",
        platform="wechat",
        channel=channel,
        channel_account_id=shared_channel_account_id,
        owner_user_id="revoked_owner",
        status="revoked",
    )
    # Active account — same channel_account_id, status == "connected"
    active = OpenClawAccountRecord(
        account_connection_id="active-acct-001",
        platform="wechat",
        channel=channel,
        channel_account_id=shared_channel_account_id,
        owner_user_id="active_owner",
        status="connected",
    )
    api_db.add(revoked)
    api_db.add(active)
    api_db.commit()

    from aivan.openclaw.contracts import OpenClawEvent
    from aivan.execution.rfq_execution import _owner_user_id_for_event

    event = OpenClawEvent(
        source="openclaw",
        channel=channel,
        channel_account_id=shared_channel_account_id,
        conversation_id="conv_owner_test",
        message_id="msg_owner_test",
        sender_id="customer_xyz",
        message_text="Need a quote.",
    )
    resolved = _owner_user_id_for_event(event, api_db)

    assert resolved == "active_owner", (
        f"Must resolve the connected account owner, not the revoked one; got {resolved!r}"
    )
