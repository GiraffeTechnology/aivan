"""Core API regressions with synthetic dependencies and SQLite, not MySQL E2E."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aivan.api import workbench_routes
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution import rfq_execution
from aivan.integrations.giraffe_db import GiraffeDBContextError
from aivan.integrations.gltg import GLTGUnavailableError
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.rfq import GiraffeContext
from tests.test_invalidated_quote_approval import _approved_quote
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
    for previous in old:
        draft = api_client.get(f"/api/drafts/{previous['draft_id']}").json()
        assert draft["status"] == "superseded"
        assert draft["message_text"] == previous["message_text"]


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
            "purchase_order_id": "unit-order"}, status="confirmed", purchase_order_id="unit-order")

    monkeypatch.setattr(workbench_routes, "_order_confirmation_client",
                        lambda **_: SimpleNamespace(confirm_order=confirm_order))
    result = api_client.post(f"/api/workbench/cases/{case_id}/order-confirmation",
        headers={"Idempotency-Key": "stale-requirement-order"}, json={"selected_option_id": option_id})
    assert result.status_code == 409, result.text
    assert calls == []


def test_material_revision_recovery_cannot_relay_old_quote(api_client, monkeypatch):
    case_id, draft_id, _ = _approved_quote(api_client, monkeypatch)
    response = _revise(api_client, monkeypatch, case_id)
    assert response.status_code == 200, response.text
    result = api_client.post(f"/api/relay/{draft_id}/confirm",
        headers={"Idempotency-Key": "stale-requirement-relay"},
        json={"receipt_reference": "synthetic-stale-manual-reference"})
    assert result.status_code == 409, result.text


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


@pytest.mark.parametrize("changed", [False, True])
def test_confirmed_projection_cannot_be_silently_rewritten(api_client, api_db, monkeypatch, changed):
    case_id, _, _ = _approved_quote(api_client, monkeypatch)
    project = ProjectRepository(api_db).get(case_id)
    # Explicit unit-only committed projection, not a live provider acceptance.
    project.requirement_json = {**project.requirement_json,
        "order_confirmation": {"status": "confirmed", "purchase_order_id": "synthetic-existing-order"}}
    api_db.commit()
    before = deepcopy(project.requirement_json)
    response = _revise(api_client, monkeypatch, case_id, failure="incomplete", changed=changed)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "CONFIRMED_ORDER_REQUIRES_AMENDMENT"
    api_db.refresh(project)
    assert project.requirement_json == before
