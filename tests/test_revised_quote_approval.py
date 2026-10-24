"""Supplier revisions cannot reuse an earlier quote's human authorization.

Explicit SQLite/API unit fixtures and synthetic dependency transports are not
real-service, MySQL, delivery or public-UI acceptance evidence.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import event, update

from aivan.api import workbench_routes
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.openclaw.client import OpenClawClient
from tests.test_rfq_execution_iteration import (
    _customer_email_event,
    _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields,
    api_client,
    api_db,
)


def _revised_quote(client, monkeypatch):
    inquiry = _customer_email_event()
    inquiry.update(channel="wechat", channel_account_id="buyer-account",
                   conversation_id="revised-quote-buyer", message_id="inquiry-revised-quote")
    created = client.post("/api/rfq/create-from-event", json=inquiry)
    assert created.status_code == 200, created.text
    case_id = created.json()["project_id"]
    sends = []

    def no_external_send(*args, **kwargs):
        sends.append((args, kwargs))
        pytest.fail("Quote review and revision must not perform an external send")

    monkeypatch.setattr(OpenClawClient, "send_message", no_external_send)
    reply = {"source": "openclaw", "channel": "email",
             "conversation_id": "revision-supplier", "sender_id": "supplier_001",
             "project_id": case_id, "role_context": "supplier", "mode": "auto"}

    def respond(version, price):
        response = client.post("/api/openclaw/events", json={**reply,
            "message_id": f"revision-{version}",
            "message_text": f"Unit price: USD {price}; MOQ 100; production lead time 35 days."})
        assert response.status_code == 200, response.text
        assert response.json()["drafts_created"]
        return response.json()

    original = respond(1, "4.50")
    original_id = original["drafts_created"][0]
    approved = client.post(f"/api/drafts/{original_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_pending_send"
    revised = respond(2, "5.50")
    assert revised["drafts_created"][0] != original_id
    assert sends == []
    return case_id, original_id, revised


def test_new_supplier_quote_reopens_review_instead_of_inheriting_approval(api_client, monkeypatch):
    case_id, _, revised = _revised_quote(api_client, monkeypatch)
    case = api_client.get(f"/api/projects/{case_id}").json()
    assert case["case_state"] == "awaiting_approval"
    assert case["selected_option"]["option_id"] == revised["requirement"]["buyer_options"][0]["option_id"]
    approved = api_client.post(f"/api/drafts/{revised['drafts_created'][0]}/approve")
    assert approved.status_code == 200, approved.text
    assert api_client.get(f"/api/projects/{case_id}").json()["case_state"] == "approved"


def test_revised_quote_blocks_order_before_new_human_approval(api_client, api_db, monkeypatch):
    case_id, _, revised = _revised_quote(api_client, monkeypatch)
    # Explicit provider-graph input, not a production fixture or approval-state jump.
    project = ProjectRepository(api_db).get(case_id)
    project.requirement_json = {**project.requirement_json,
        "giraffe_db_graph": {"procurement_case_id": "unit-case", "rfq_id": "unit-rfq"}}
    api_db.commit()
    calls = []

    def confirm_order(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {
            "procurement_case_id": "unit-case", "supplier_quote_id": "unit-quote",
            "purchase_order_id": "unit-order", "status": "confirmed", "readback_verified": True},
            purchase_order_id="unit-order", status="confirmed", readback_verified=True)

    monkeypatch.setattr(workbench_routes, "_order_confirmation_client",
                        lambda **_: SimpleNamespace(confirm_order=confirm_order))
    result = api_client.post(f"/api/workbench/cases/{case_id}/order-confirmation",
        headers={"Idempotency-Key": "revised-quote-not-approved"},
        json={"selected_option_id": revised["requirement"]["buyer_options"][0]["option_id"]})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error"] == "ORDER_CONFIRMATION_INVALID_CASE_STATE"
    assert calls == []


def test_old_approved_manual_draft_is_not_actionable_after_revision(api_client, monkeypatch):
    case_id, old_draft_id, revised = _revised_quote(api_client, monkeypatch)
    old = api_client.get(f"/api/drafts/{old_draft_id}").json()
    assert old["status"] == "superseded"
    result = api_client.post(f"/api/relay/{old_draft_id}/confirm",
        headers={"Idempotency-Key": "old-revision-relay"},
        json={"receipt_reference": "old-manual-receipt"})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error"] == "INVALID_DRAFT_STATE"
    current = api_client.get(f"/api/drafts/{revised['drafts_created'][0]}").json()
    assert current["status"] == "pending_approval"


@pytest.mark.parametrize("status", ["pending_approval", "approved", "approved_pending_send", "send_failed"])
def test_superseding_revokes_only_unsent_old_quote_authorizations(db_session, status):
    repo = DraftRepository(db_session)
    draft = repo.create("quote-revision-case", {"tenant_id": "tenant-a", "status": status,
        "message_text": "Old quote", "notes": "draft_type=customer_quote_email"})
    inquiry = repo.create("quote-revision-case", {"tenant_id": "tenant-a", "status": status,
        "message_text": "Supplier inquiry", "notes": "draft_type=supplier_inquiry_email"})
    assert repo.supersede_customer_quote_drafts("quote-revision-case") == [draft.draft_id]
    assert draft.status == "superseded"
    assert inquiry.status == status


@pytest.mark.parametrize("status", ["sent", "relayed", "delivery_unconfirmed", "rejected", "superseded"])
def test_quote_revision_preserves_delivered_uncertain_and_rejected_history(db_session, status):
    repo = DraftRepository(db_session)
    draft = repo.create("quote-revision-case", {"tenant_id": "tenant-a", "status": status,
        "message_text": "Historical quote", "notes": "draft_type=customer_quote_email"})
    assert repo.supersede_customer_quote_drafts("quote-revision-case") == []
    assert draft.status == status


def test_delivery_claim_between_snapshot_and_supersede_is_not_overwritten(db_session):
    repo = DraftRepository(db_session)
    draft = repo.create("quote-revision-case", {"tenant_id": "tenant-a", "status": "approved",
        "message_text": "Old quote", "notes": "draft_type=customer_quote_email"})
    db_session.commit()
    interleaved = []

    def claim_before_supersede(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("UPDATE ") and not interleaved:
            interleaved.append(True)
            connection.execute(update(InquiryDraftRecord).where(
                InquiryDraftRecord.draft_id == draft.draft_id
            ).values(status="delivery_unconfirmed"))

    event.listen(db_session.bind, "before_cursor_execute", claim_before_supersede)
    try:
        assert repo.supersede_customer_quote_drafts("quote-revision-case") == []
        assert interleaved == [True]
        assert draft.status == "delivery_unconfirmed"
    finally:
        event.remove(db_session.bind, "before_cursor_execute", claim_before_supersede)
