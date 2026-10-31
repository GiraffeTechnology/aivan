"""Synthetic transports prove lost acknowledgements never enable duplicate sends."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aivan.db.models import Base
from aivan.db.repositories.draft_repo import DraftRepository
from aivan.execution.approval_state import DraftStateError, approve_and_send
from aivan.execution.draft_preview import bind_approval, create_preview
from aivan.openclaw.client import OpenClawClient
from aivan.openclaw.contracts import OpenClawSendRequest
from aivan.openclaw.outbound_approval import send_if_approved
from tests.test_localized_draft_preview import (  # noqa: F401
    FRENCH, approve, assert_no_localized_rows, boundary, preview, setup_draft,
)
from tests.test_stage4_relay import _draft, _tenant_headers, relay_api  # noqa: F401


def client_for_transport(monkeypatch, handler):
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "false")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "https://synthetic-gateway.example.invalid")
    monkeypatch.setattr("aivan.openclaw.client.httpx.post", handler)
    sender = OpenClawClient()
    monkeypatch.setattr("aivan.openclaw.outbound_approval.get_openclaw_client", lambda: sender)
    monkeypatch.setattr("aivan.execution.approval_state.get_openclaw_client", lambda: sender)
    return sender


def test_accepted_request_with_lost_ack_blocks_retry_and_new_preview(relay_api, boundary, monkeypatch):
    calls = []
    def accepted_then_timeout(url, **kwargs):
        calls.append(kwargs["json"])
        raise httpx.ReadTimeout("Synthetic lost acknowledgement")
    client_for_transport(monkeypatch, accepted_then_timeout)
    client, db, draft = setup_draft(relay_api)
    proof = preview(client, draft).json()
    result = approve(client, draft, proof)
    assert result.status_code == 200 and result.json()["status"] == "delivery_unconfirmed"
    assert calls[0]["message_text"] == FRENCH
    assert client.post(f"/api/drafts/{draft.draft_id}/retry", headers=_tenant_headers()).status_code == 409
    assert approve(client, draft, proof).status_code == 409
    assert preview(client, draft).status_code == 409
    assert len(calls) == 1
    assert_no_localized_rows(db)


@pytest.mark.parametrize("status,payload,uncertain", [
    (503, {"error": "unavailable"}, True),
    (403, {"error": "rejected"}, False),
    (200, {}, True),
    (200, {"success": True}, True),
    (200, {"success": "true", "message_id": "x"}, True),
    (200, {"success": False}, False),
    (200, {"success": True, "message_id": "ack-1"}, False),
])
def test_transport_requires_explicit_well_formed_acknowledgement(monkeypatch, status, payload, uncertain):
    def transport(url, **kwargs):
        return httpx.Response(status, json=payload, request=httpx.Request("POST", url))
    sender = client_for_transport(monkeypatch, transport)
    result = sender.send_message(OpenClawSendRequest(channel="email", conversation_id="synthetic", target_peer_id="supplier@example.invalid", message_text="This is a synthetic message."))
    assert result.outcome_uncertain is uncertain
    assert result.success is (status == 200 and payload == {"success": True, "message_id": "ack-1"})


@pytest.mark.parametrize("interrupted", [False, True])
def test_durable_delivery_claim_survives_transport_loss_and_process_interruption(tmp_path, boundary, monkeypatch, interrupted):
    calls = []
    class Sender:
        def send_message(self, request):
            calls.append(request)
            if interrupted:
                raise SystemExit("Synthetic process interruption after submission")
            raise httpx.ReadTimeout("Synthetic lost acknowledgement")
    monkeypatch.setattr("aivan.openclaw.outbound_approval.get_openclaw_client", lambda: Sender())
    url = f"sqlite:///{tmp_path / 'delivery.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        draft = _draft(db, channel="email")
        proof, _ = create_preview(db, draft, "fr")
        draft.status = "approved"
        draft.approval_id = "synthetic-approved-render"
        bind_approval(db, draft, proof)
        draft_id = draft.draft_id
        db.commit()
        if interrupted:
            with pytest.raises(SystemExit):
                send_if_approved(draft_id, db)
        else:
            result = send_if_approved(draft_id, db)
            assert result.outcome_uncertain
        # Deliberately do not commit after transport. The claim was durable first.
    engine.dispose()
    engine = create_engine(url)
    with Session(engine) as db:
        assert DraftRepository(db).get(draft_id).status == "delivery_unconfirmed"
        assert send_if_approved(draft_id, db).success is False
        with pytest.raises(DraftStateError):
            approve_and_send(draft_id, db)
        assert len(calls) == 1 and calls[0].message_text == FRENCH
        assert_no_localized_rows(db)
    engine.dispose()


def test_smtp_lost_ack_is_unconfirmed_and_not_retried(db_session, monkeypatch):
    from tests.test_real_test_email_transport import _draft as smtp_draft, _real_test_env
    _real_test_env(monkeypatch)
    calls = []
    class SMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, *args):
            pass
        def send_message(self, message, **kwargs):
            calls.append(message)
            raise TimeoutError("Synthetic SMTP acknowledgement loss")
    monkeypatch.setattr("aivan.openclaw.email_transport.smtplib.SMTP_SSL", SMTP)
    draft_id = smtp_draft(db_session, target="approved.recipient@example.invalid")
    response = send_if_approved(draft_id, db_session)
    assert response.outcome_uncertain and not response.success
    assert DraftRepository(db_session).get(draft_id).status == "delivery_unconfirmed"
    assert send_if_approved(draft_id, db_session).success is False
    assert len(calls) == 1
