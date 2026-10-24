"""Actual RFQ/approval APIs with explicit SQLite and synthetic dependencies."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event, update

from aivan.api import workbench_routes
from aivan.db.models.domain import AuditLogRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution.draft_preview import invalidate_approval
from aivan.openclaw.client import OpenClawClient
from aivan.openclaw.contracts import OpenClawSendResponse
from tests.test_revised_quote_approval import _revised_quote
from tests.test_rfq_execution_iteration import (
    _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields,
    api_client,
    api_db,
)


def _approved_quote(client, monkeypatch):
    case_id, _, revised = _revised_quote(client, monkeypatch)
    draft_id = revised["drafts_created"][0]
    preview = client.post(f"/api/drafts/{draft_id}/preview", json={"target_language": "en"})
    assert preview.status_code == 200, preview.text
    approved = client.post(f"/api/drafts/{draft_id}/approve",
                           json={"preview_id": preview.json()["preview_id"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved_pending_send"
    assert client.get(f"/api/projects/{case_id}").json()["case_state"] == "approved"
    return case_id, draft_id, preview.json()


def _new_preview(client, draft_id):
    result = client.post(f"/api/drafts/{draft_id}/preview", json={"target_language": "en"})
    assert result.status_code == 200, result.text
    draft = client.get(f"/api/drafts/{draft_id}").json()
    assert draft["status"] == "pending_approval"
    assert not draft["approved_by"]
    return result.json()


def test_repreview_revokes_case_approval_until_current_draft_review(api_client, monkeypatch):
    case_id, draft_id, _ = _approved_quote(api_client, monkeypatch)
    new_preview = _new_preview(api_client, draft_id)
    assert api_client.get(f"/api/projects/{case_id}").json()["case_state"] == "awaiting_approval"
    approved = api_client.post(f"/api/drafts/{draft_id}/approve",
                               json={"preview_id": new_preview["preview_id"]})
    assert approved.status_code == 200, approved.text
    assert api_client.get(f"/api/projects/{case_id}").json()["case_state"] == "approved"


def test_invalidated_preview_cannot_authorize_an_order(api_client, api_db, monkeypatch):
    case_id, draft_id, _ = _approved_quote(api_client, monkeypatch)
    _new_preview(api_client, draft_id)
    project = ProjectRepository(api_db).get(case_id)
    project.requirement_json = {**project.requirement_json,
        "giraffe_db_graph": {"procurement_case_id": "unit-case", "rfq_id": "unit-rfq"}}
    api_db.commit()
    calls = []

    def confirm_order(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {"status": "confirmed", "readback_verified": True,
            "procurement_case_id": "unit-case", "supplier_quote_id": "unit-quote",
            "purchase_order_id": "unit-order"}, status="confirmed",
            purchase_order_id="unit-order", readback_verified=True)

    monkeypatch.setattr(workbench_routes, "_order_confirmation_client",
                        lambda **_: SimpleNamespace(confirm_order=confirm_order))
    result = api_client.post(f"/api/workbench/cases/{case_id}/order-confirmation",
        headers={"Idempotency-Key": "revoked-preview-order"},
        json={"selected_option_id": project.selected_option_json["option_id"]})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error"] == "ORDER_CONFIRMATION_INVALID_CASE_STATE"
    assert calls == []


def test_invalid_manual_receipt_proof_cannot_leave_case_approved(api_client, monkeypatch):
    case_id, draft_id, preview = _approved_quote(api_client, monkeypatch)
    result = api_client.post(f"/api/relay/{draft_id}/confirm",
        headers={"Idempotency-Key": "wrong-current-preview"},
        json={"receipt_reference": "synthetic-receipt", "preview_id": preview["preview_id"],
              "content_sha256": "0" * 64})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error"] == "RELAY_PREVIEW_VERSION_MISMATCH"
    assert api_client.get(f"/api/drafts/{draft_id}").json()["status"] == "pending_approval"
    assert api_client.get(f"/api/projects/{case_id}").json()["case_state"] == "awaiting_approval"


def test_supplier_inquiry_approval_does_not_approve_customer_quote(api_client, monkeypatch):
    case_id, _, revised = _revised_quote(api_client, monkeypatch)
    drafts = api_client.get(f"/api/projects/{case_id}/drafts").json()["drafts"]
    supplier = next(d for d in drafts if d["target_role"] == "supplier" and d["status"] == "pending_approval")
    # Explicitly human-authorized synthetic supplier send, not an automatic or
    # real customer/platform action. It cannot approve the different buyer quote.
    sends = []

    def synthetic_send(self, request):
        sends.append(request)
        return OpenClawSendResponse(success=True, message_id="unit-supplier-send")

    monkeypatch.setattr(OpenClawClient, "send_message", synthetic_send)
    result = api_client.post(f"/api/drafts/{supplier['draft_id']}/approve")
    assert result.status_code == 200, result.text
    assert len(sends) == 1
    assert api_client.get(f"/api/drafts/{revised['drafts_created'][0]}").json()["status"] == "pending_approval"
    assert api_client.get(f"/api/projects/{case_id}").json()["case_state"] == "awaiting_approval"


def _invalidation_fixture(db, *, draft_type="customer_quote_email", status="approved"):
    project = ProjectRepository(db).create("approval-unit", "buyer-unit", tenant_id="tenant-a")
    project.case_state = "approved"
    draft = DraftRepository(db).create(project.project_id, {"tenant_id": "tenant-a",
        "message_text": "Please review the quotation.", "status": status,
        "approval_id": "observed-approval", "approved_by": "approver-unit",
        "notes": "draft_type=" + draft_type})
    db.commit()
    return project, draft


@pytest.mark.parametrize("status", ["sent", "relayed", "delivery_unconfirmed", "rejected", "superseded"])
def test_invalidating_review_cannot_resurrect_terminal_or_unknown_delivery(db_session, status):
    project, draft = _invalidation_fixture(db_session, status=status)
    invalidate_approval(db_session, draft, "CONTROLLED_PREVIEW_CHANGE")
    assert draft.status == status
    assert draft.approval_id == "observed-approval"
    assert project.case_state == "approved"
    assert db_session.query(AuditLogRecord).filter_by(event_type="DRAFT_APPROVAL_INVALIDATED").count() == 0


def test_invalidating_supplier_review_does_not_revoke_customer_case_approval(db_session):
    project, draft = _invalidation_fixture(db_session, draft_type="supplier_inquiry_email")
    invalidate_approval(db_session, draft, "CONTROLLED_PREVIEW_CHANGE")
    assert draft.status == "pending_approval"
    assert project.case_state == "approved"


def test_invalidating_review_does_not_rewrite_already_committed_order(db_session):
    project, draft = _invalidation_fixture(db_session)
    project.status = "order_confirmed"
    project.requirement_json = {"order_confirmation": {"status": "confirmed", "purchase_order_id": "unit-order"}}
    db_session.commit()
    invalidate_approval(db_session, draft, "CONTROLLED_PREVIEW_CHANGE")
    assert draft.status == "pending_approval"
    assert project.status == "order_confirmed"
    assert project.case_state == "approved"
    assert project.requirement_json["order_confirmation"]["purchase_order_id"] == "unit-order"


@pytest.mark.parametrize("interleave", ["new-approval", "delivery-claim"])
def test_stale_invalidation_cannot_overwrite_new_approval_or_delivery_claim(db_session, interleave):
    project, draft = _invalidation_fixture(db_session)
    applied = []

    def before_invalidation(connection, cursor, statement, parameters, context, many):
        if (statement.lstrip().upper().startswith("UPDATE INQUIRY_DRAFTS") and not applied):
            applied.append(True)
            values = {"approval_id": "newer-approval"} if interleave == "new-approval" else {"status": "delivery_unconfirmed"}
            connection.execute(update(InquiryDraftRecord).where(
                InquiryDraftRecord.draft_id == draft.draft_id).values(**values))

    event.listen(db_session.bind, "before_cursor_execute", before_invalidation)
    try:
        invalidate_approval(db_session, draft, "CONTROLLED_PREVIEW_CHANGE")
        assert applied == [True]
        assert draft.status == ("approved" if interleave == "new-approval" else "delivery_unconfirmed")
        assert draft.approval_id == ("newer-approval" if interleave == "new-approval" else "observed-approval")
        assert project.case_state == "approved"
        assert db_session.query(AuditLogRecord).filter_by(event_type="DRAFT_APPROVAL_INVALIDATED").count() == 0
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_invalidation)
