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
    assert "pending approval" in payload["user_control_message"].lower()

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


def test_gltg_timeout_fallback(monkeypatch):
    monkeypatch.setenv("AIVAN_GLTG_FORCE_TIMEOUT", "true")
    simulation = GLTGClient().simulate(
        BuyerRequirement(category="apparel", product_type="shirt", quantity=10000, destination="Vancouver", delivery_days=45),
        RFQStrategy(lead_time_confidence="P80"),
        supplier_count=2,
    )

    assert simulation.known_suppliers_first_feasibility == "unknown_due_to_timeout"
    assert simulation.deadline_risk_level == "high"
    assert "timed out" in simulation.explanation


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
