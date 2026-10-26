"""Core API regressions with synthetic dependencies and SQLite, not MySQL E2E."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aivan.api import workbench_routes
from aivan.db.models.domain import AuditLogRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.project import Project
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution import rfq_execution
from aivan.execution.approval_state import DraftStateError
from aivan.integrations.giraffe_db import GiraffeDBContextError
from aivan.integrations.gltg import GLTGUnavailableError
from aivan.schemas.requirement import BuyerRequirement
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.rfq import EventClassification, GiraffeContext
from tests.test_invalidated_quote_approval import _approved_quote
from tests.test_quote_rejection_concurrency import records, reject
from tests.test_rfq_execution_iteration import (
    _customer_email_event,
    _explicit_unit_supplier_dataset,
    _language_skill_resolves_canonical_fields,
    api_client,
    api_db,
)


def _revise(client, monkeypatch, case_id, *, failure="gltg", changed=True):
    before = client.get(f"/api/projects/{case_id}").json()
    requirement = BuyerRequirement.model_validate(before["requirement"]).model_copy(deep=True)
    if changed:
        requirement.quantity = (requirement.quantity or 10000) + 1000
    if failure == "incomplete":
        requirement.product_type = None
    requirement.raw_text = "Please update the inquiry using these revised requirement details."
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm",
                        lambda **_: requirement.model_copy(deep=True))
    monkeypatch.setattr(rfq_execution, "_send_user_control_notification",
                        lambda *args, **kwargs: {"status": "not_sent"})

    def unavailable(*args, **kwargs):
        if failure == "gltg":
            raise GLTGUnavailableError("GLTG_UNAVAILABLE")
        if failure == "context":
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_UNAVAILABLE")
        raise RuntimeError("GIRAFFE_DB_GRAPH_INDETERMINATE_COMMIT:comparison-snapshot")

    if failure == "gltg":
        monkeypatch.setattr(rfq_execution.GLTGClient, "simulate", unavailable)
    elif failure == "context":
        monkeypatch.setattr(rfq_execution.GiraffeDBClient, "build_context", unavailable)
    elif failure == "graph":
        monkeypatch.setattr(rfq_execution, "persist_rfq_gltg_graph", unavailable)
    elif failure == "suppliers":
        monkeypatch.setattr(rfq_execution.GiraffeDBClient, "build_context",
                            lambda *args, **kwargs: GiraffeContext())
    body = {**_customer_email_event(), "channel": "wechat", "channel_account_id": "buyer-account",
            "conversation_id": "revised-quote-buyer", "project_id": case_id,
            "message_id": f"requirement-revision-{failure}-{changed}",
            "message_text": requirement.raw_text}
    return client.post("/api/rfq/create-from-event", json=body)


@pytest.mark.parametrize("failure", ["gltg", "context", "graph", "suppliers", "incomplete"])
def test_material_inbound_revision_invalidates_old_approval_before_pending(
    api_client, api_db, monkeypatch, failure,
):
    case_id, quote_draft, _ = _approved_quote(api_client, monkeypatch)
    before = api_client.get(f"/api/projects/{case_id}/drafts").json()["drafts"]
    old = [row for row in before if row["status"] in {
        "pending_approval", "approved", "approved_pending_send", "send_failed",
    } and any(tag in (row.get("notes") or "") for tag in (
        "draft_type=customer_quote_email", "draft_type=supplier_inquiry_email",
    ))]
    assert quote_draft in [row["draft_id"] for row in old]
    response = _revise(api_client, monkeypatch, case_id, failure=failure)
    assert response.status_code == 200, response.text
    assert response.json()["drafts_created"] == []
    current = api_client.get(f"/api/projects/{case_id}").json()
    assert current["selected_option"] is None
    assert current["case_state"] != "approved"
    assert not current["requirement"].get("buyer_options")
    for key in ("supplier_replies", "lead_time_estimates", "gltg_simulation", "gpm_guidance", "giraffe_db_graph"):
        assert not current["requirement"].get(key)
    for previous in old:
        draft = api_client.get(f"/api/drafts/{previous['draft_id']}").json()
        assert draft["status"] == "superseded"
        assert draft["message_text"] == previous["message_text"]
    assert api_client.post(f"/api/drafts/{quote_draft}/approve").status_code == 409
    audit = api_db.query(AuditLogRecord).filter_by(
        case_id=case_id, event_type="REQUIREMENT_APPROVAL_INVALIDATED").one()
    assert "quantity" in audit.after_json["changed_fields"]
    assert audit.actor_id


def test_material_revision_recovery_cannot_confirm_old_order(api_client, api_db, monkeypatch):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    project = ProjectRepository(api_db).get(case_id)
    option_id = project.selected_option_json["option_id"]
    # Synthetic provider reference, not a production graph or order commit.
    project.requirement_json = {**project.requirement_json,
        "giraffe_db_graph": {"procurement_case_id": "unit-case", "rfq_id": "unit-rfq"}}
    api_db.commit()
    response = _revise(api_client, monkeypatch, case_id)
    assert response.status_code == 200, response.text
    calls = []

    def confirm_order(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(as_dict=lambda: {"status": "confirmed", "readback_verified": True,
            "procurement_case_id": "unit-case", "supplier_quote_id": "unit-quote",
            "purchase_order_id": "unit-order"}, status="confirmed", purchase_order_id="unit-order",
            readback_verified=True)

    monkeypatch.setattr(workbench_routes, "_order_confirmation_client",
                        lambda **_: SimpleNamespace(confirm_order=confirm_order))
    result = api_client.post(f"/api/workbench/cases/{case_id}/order-confirmation",
        headers={"Idempotency-Key": "stale-requirement-order"}, json={"selected_option_id": option_id})
    assert calls == []
    assert result.status_code == 409, result.text


def test_material_revision_recovery_cannot_relay_old_quote(api_client, monkeypatch):
    case_id, draft_id, preview = _approved_quote(api_client, monkeypatch)
    response = _revise(api_client, monkeypatch, case_id)
    assert response.status_code == 200, response.text
    result = api_client.post(f"/api/relay/{draft_id}/confirm",
        headers={"Idempotency-Key": "stale-requirement-relay"},
        json={"receipt_reference": "synthetic-stale-manual-reference",
              "preview_id": preview["preview_id"], "content_sha256": preview["rendered_sha256"]})
    assert result.status_code == 409, result.text
    assert result.json()["detail"]["error"] == "INVALID_DRAFT_STATE"


@pytest.mark.parametrize("failure", ["gltg", "context", "graph"])
def test_same_commercial_facts_do_not_blanket_revoke_approval(api_client, monkeypatch, failure):
    case_id, draft_id, _ = _approved_quote(api_client, monkeypatch)
    before = api_client.get(f"/api/projects/{case_id}").json()
    response = _revise(api_client, monkeypatch, case_id, failure=failure, changed=False)
    assert response.status_code == 200, response.text
    current = api_client.get(f"/api/projects/{case_id}").json()
    assert current["selected_option"] == before["selected_option"]
    assert current["case_state"] == "approved"
    assert api_client.get(f"/api/drafts/{draft_id}").json()["status"] == "approved_pending_send"


def test_successful_material_revision_requires_fresh_inquiry_review(api_client, monkeypatch):
    case_id, old_quote_id, _ = _approved_quote(api_client, monkeypatch)
    response = _revise(api_client, monkeypatch, case_id, failure="none")
    assert response.status_code == 200, response.text
    assert response.json()["drafts_created"]
    current = api_client.get(f"/api/projects/{case_id}").json()
    assert current["selected_option"] is None
    assert current["case_state"] != "approved"
    assert api_client.get(f"/api/drafts/{old_quote_id}").json()["status"] == "superseded"
    for draft_id in response.json()["drafts_created"]:
        assert api_client.get(f"/api/drafts/{draft_id}").json()["status"] == "pending_approval"


@pytest.mark.parametrize("failure", ["incomplete", "gltg"])
def test_confirmed_projection_cannot_be_silently_rewritten(api_client, api_db, monkeypatch, failure):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    project = ProjectRepository(api_db).get(case_id)
    # Explicit unit-only committed projection, not a live provider acceptance.
    project.requirement_json = {**project.requirement_json,
        "order_confirmation": {"status": "confirmed", "purchase_order_id": "synthetic-existing-order"}}
    api_db.commit()
    before = deepcopy(project.requirement_json)
    response = _revise(api_client, monkeypatch, case_id, failure=failure)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "CONFIRMED_ORDER_REQUIRES_AMENDMENT"
    api_db.refresh(project)
    assert project.requirement_json == before


@pytest.mark.parametrize("status", ["sent", "relayed", "delivery_unconfirmed", "sending"])
def test_material_revision_preserves_delivery_history(api_client, api_db, monkeypatch, status):
    case_id, draft_id, _ = _approved_quote(api_client, monkeypatch)
    draft = DraftRepository(api_db).get(draft_id)
    draft.status = status
    api_db.commit()
    before = draft.message_text
    assert _revise(api_client, monkeypatch, case_id).status_code == 200
    api_db.refresh(draft)
    assert draft.status == status
    assert draft.message_text == before


@pytest.mark.parametrize("status", ["completed", "cancelled", "qc", "logistics"])
def test_material_revision_does_not_reopen_terminal_case(api_client, api_db, monkeypatch, status):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    project = ProjectRepository(api_db).get(case_id)
    project.case_state = status
    api_db.commit()
    before = deepcopy(project.requirement_json)
    response = _revise(api_client, monkeypatch, case_id)
    assert response.status_code == 409, response.text
    api_db.refresh(project)
    assert project.case_state == status
    assert project.requirement_json == before


def test_material_revision_receipt_replays_without_second_invalidation(api_client, api_db, monkeypatch):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    first = _revise(api_client, monkeypatch, case_id)
    assert first.status_code == 200, first.text
    before = api_client.get(f"/api/projects/{case_id}").json()
    drafts = api_client.get(f"/api/projects/{case_id}/drafts").json()
    second = _revise(api_client, monkeypatch, case_id)
    assert second.status_code == 200, second.text
    assert second.json()["requirement"] == first.json()["requirement"]
    assert api_client.get(f"/api/projects/{case_id}").json()["requirement"] == before["requirement"]
    assert api_client.get(f"/api/projects/{case_id}/drafts").json() == drafts
    assert api_db.query(AuditLogRecord).filter_by(
        case_id=case_id, event_type="REQUIREMENT_APPROVAL_INVALIDATED").count() == 1


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("first_lane", ["revise", "decision"])
def test_requirement_revision_and_decision_transaction_orderings(records, monkeypatch, first_lane, decision):
    """Controlled SQLite interleavings, not MySQL or real-provider acceptance."""
    sessions, (pid, did) = records
    with sessions() as db:
        draft = db.get(InquiryDraftRecord, did)
        draft.channel = "wechat"
        draft.channel_account_id = "synthetic-account"
        draft.conversation_id = "test-thread"
        db.commit()
    monkeypatch.setattr(rfq_execution, "classify_event", lambda *a: EventClassification(
        event_type="customer_followup", project_id=pid, confidence=1, reason="synthetic revision"))
    monkeypatch.setattr(rfq_execution, "_get_or_create_project", lambda event, classification, db: db.get(Project, pid))
    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm", lambda **kwargs:
                        kwargs["existing_requirement"].model_copy(update={"quantity": 11}))
    monkeypatch.setattr(rfq_execution, "_send_user_control_notification", lambda *a: {"status": "not_sent"})
    locked, attempted, done = Event(), Event(), Event()
    original = ProjectRepository.get_for_update

    def lock(repo, *args, **kwargs):
        if repo.db.info["lane"] != first_lane:
            attempted.set()
            result = original(repo, *args, **kwargs)
            assert done.wait(5)
            return result
        result = original(repo, *args, **kwargs)
        locked.set()
        assert attempted.wait(5)
        return result

    monkeypatch.setattr(ProjectRepository, "get_for_update", lock)

    def run(lane):
        with sessions() as db:
            db.info["lane"] = lane
            retained = db.get(Project, pid)
            draft = db.get(InquiryDraftRecord, did)
            if lane != first_lane:
                assert locked.wait(5)
            try:
                if lane == "decision":
                    if decision == "reject":
                        reject(db, draft)
                        db.commit()
                    else:
                        from aivan.api.main import _do_approve_draft
                        result = _do_approve_draft(did, db, SimpleNamespace(
                            tenant_id="race", trace_id="race-approval", idempotency_key="race-approval",
                            actor_id="approver", role_context="approver", conversation_role="",
                            execution_mode="approval", authorization_basis="unit-principal", production=False))
                        assert result["status"] == "approved_pending_send"
                        assert result["sent"] is False
                else:
                    result = rfq_execution._create_rfq_from_event_inner(OpenClawEvent(
                        tenant_id="race", project_id=pid, channel="wechat", conversation_id="test-thread",
                        sender_id="buyer", actor_id="buyer", business_role="buyer",
                        message_text="Change quantity to eleven.", source_trace_id="race-revision"), db)
                    assert not result.drafts_created
                assert retained is not None
                return "committed"
            except DraftStateError:
                db.rollback()
                return "conflict"
            except HTTPException as exc:
                assert exc.status_code == 409
                db.rollback()
                return "conflict"
            finally:
                if lane == first_lane:
                    done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, first_lane)
        b = pool.submit(run, "decision" if first_lane == "revise" else "revise")
        assert a.result(timeout=15) == "committed"
        assert b.result(timeout=15) == ("conflict" if first_lane == "revise" else "committed")
    with sessions() as db:
        assert db.get(Project, pid).case_state == "inquiry"
        assert db.get(Project, pid).requirement_json["quantity"] == 11
        assert db.get(InquiryDraftRecord, did).status == (
            "rejected" if first_lane == "decision" and decision == "reject" else "superseded")
        assert db.query(AuditLogRecord).filter_by(event_type="REQUIREMENT_APPROVAL_INVALIDATED").count() == 1
