"""API result text reflects persisted draft outcomes; isolated unit services only."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent
from aivan.openclaw.client import OpenClawClient
from tests.test_rfq_execution_iteration import (
    _customer_email_event,
    _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields,
    api_client,
    api_db,
)


@pytest.mark.parametrize("buyer_channel", ["email", "wechat"])
@pytest.mark.parametrize("price_available", [True, False])
def test_reply_message_matches_actual_customer_draft_state(
    api_client, monkeypatch, buyer_channel, price_available,
):
    suffix = f"{buyer_channel}-{price_available}"
    inquiry = _customer_email_event()
    inquiry.update(channel=buyer_channel, conversation_id="buyer-outcome-" + suffix,
                   message_id="inquiry-outcome-" + suffix)
    created = api_client.post("/api/rfq/create-from-event", json=inquiry)
    assert created.status_code == 200, created.text
    case_id = created.json()["project_id"]
    before_event_ids = {
        event["event_id"] for event in
        api_client.get(f"/api/projects/{case_id}/events").json()["events"]
    }

    def unavailable(*_args):
        raise RuntimeError("controlled extraction model unavailable")

    monkeypatch.setattr(supplier_response_agent, "llm_complete_json", unavailable)
    sends = []

    def must_not_send(*args, **kwargs):
        sends.append((args, kwargs))
        pytest.fail("Supplier reply processing must not send the customer draft")

    monkeypatch.setattr(OpenClawClient, "send_message", must_not_send)
    text = "MOQ 100; production lead time 35 days."
    text = ("Unit price: USD 4.50; " if price_available else "Unit price not confirmed; ") + text
    response = api_client.post("/api/openclaw/events", json={
        "source": "openclaw", "channel": "email", "conversation_id": "supplier-outcome-" + suffix,
        "message_id": "supplier-reply-" + suffix, "sender_id": "supplier_001",
        "project_id": case_id, "message_text": text, "role_context": "supplier", "mode": "auto",
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["event_type"] == "supplier_reply"
    assert sends == []
    drafts = api_client.get(f"/api/projects/{case_id}/drafts").json()["drafts"]
    customer_drafts = [draft for draft in drafts if draft["target_role"] == "customer"]
    if price_available:
        assert payload["action"] == "buyer_options_ready"
        assert len(customer_drafts) == 1
        assert payload["drafts_created"] == [customer_drafts[0]["draft_id"]]
        assert customer_drafts[0]["status"] == "pending_approval"
        assert customer_drafts[0]["channel"] == buyer_channel
        assert "pending approval" in payload["message"].lower()
        if buyer_channel != "email":
            assert "email" not in payload["message"].lower()
            events = api_client.get(f"/api/projects/{case_id}/events").json()["events"]
            quote_events = [event for event in events
                            if event["event_type"] == "PENDING_EMAIL_DRAFT_CREATED"
                            and event["event_id"] not in before_event_ids]
            assert len(quote_events) == 1
            assert "email" not in quote_events[0]["summary"].lower()
    else:
        assert payload["action"] == "supplier_reply_parsed"
        assert payload["drafts_created"] == []
        assert customer_drafts == []
        assert "pending approval" not in payload["message"].lower()
        assert "No customer quote draft was created." in payload["message"]
