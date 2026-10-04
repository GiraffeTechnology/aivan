"""SQLite unit readback; not CTYun MySQL or live-provider acceptance."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from aivan.db.models import Project
from aivan.execution import rfq_execution
from aivan.integrations.giraffe_db import GiraffeDBContextError
from aivan.openclaw.contracts import OpenClawEvent
from aivan.schemas.rfq import GiraffeContext
from tests.test_inbound_english_persistence import ENGLISH, RAW, translator  # noqa: F401


@pytest.mark.parametrize("mode, action", [
    ("none", "pending_supplier_selection"),
    ("uncontactable", "pending_supplier_selection"),
    ("dependency", "pending_dependency_recovery"),
])
def test_ready_requirement_survives_pending_path_and_session_reopen(
    mode, action, translator, db_session, monkeypatch,
):
    calls = []
    def context(*args, **kwargs):
        if mode == "dependency":
            raise GiraffeDBContextError("GIRAFFE_DB_CONTEXT_UNAVAILABLE")
        suppliers = [{"supplier_id": "synthetic-supplier", "name": "Synthetic supplier", "email": ""}] if mode == "uncontactable" else []
        return GiraffeContext(suppliers=suppliers)
    monkeypatch.setattr(rfq_execution.GiraffeDBClient, "build_context", context)
    def forbidden(*args, **kwargs):
        calls.append("downstream")
        raise AssertionError("Pending path must not calculate or draft")
    monkeypatch.setattr(rfq_execution.GLTGClient, "simulate", forbidden)
    monkeypatch.setattr(rfq_execution, "_create_supplier_email_drafts", forbidden)
    monkeypatch.setattr(rfq_execution, "_send_user_control_notification", lambda *args: {"status": "not_sent"})
    event = OpenClawEvent(tenant_id="unit-tenant", conversation_id=f"pending-{mode}",
                          sender_id="buyer", business_role="buyer", message_text=RAW,
                          message_id=f"pending-message-{mode}")
    result = rfq_execution.create_rfq_from_event(event, db_session)
    assert result.action == action
    assert result.drafts_created == []
    assert calls == []
    db_session.commit()
    with Session(bind=db_session.get_bind()) as reopened:
        row = reopened.get(Project, result.project_id)
        assert row.tenant_id == "unit-tenant"
        assert row.requirement_json["raw_text"] == ENGLISH
        assert row.requirement_json["quantity"] == 5000
        assert row.requirement_json["destination"] == "Tokyo"
    replay = rfq_execution.create_rfq_from_event(event, db_session)
    assert replay.project_id == result.project_id
    assert replay.action == result.action
    assert db_session.query(Project).count() == 1
    assert calls == []


def test_pending_commit_failure_never_returns_success(translator, db_session, monkeypatch):
    monkeypatch.setattr(rfq_execution.GiraffeDBClient, "build_context", lambda *args, **kwargs: GiraffeContext())
    monkeypatch.setattr(rfq_execution, "_send_user_control_notification", lambda *args: {"status": "not_sent"})
    def fail_commit():
        raise RuntimeError("synthetic persistence failure")
    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        rfq_execution.create_rfq_from_event(OpenClawEvent(
            tenant_id="unit-tenant", conversation_id="pending-failure", sender_id="buyer",
            business_role="buyer", message_text=RAW, message_id="failure-message"), db_session)
    db_session.rollback()
    assert db_session.query(Project).count() == 0
