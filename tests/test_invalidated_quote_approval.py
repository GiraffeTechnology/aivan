"""Actual RFQ/approval APIs with explicit SQLite and synthetic dependencies."""
from types import SimpleNamespace

from aivan.api import workbench_routes
from aivan.db.repositories.project_repo import ProjectRepository
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
