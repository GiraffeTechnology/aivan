"""Stage 2 trusted request identity boundary tests."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aivan.api.request_context import RequestContext, apply_trusted_identity


def _context(**overrides):
    values = dict(
        tenant_id="tenant-a",
        trace_id="trace-1",
        idempotency_key="delivery-1",
        actor_id="actor-1",
        role_context="buyer",
        conversation_role="buyer_thread",
        execution_mode="auto",
        channel_account_id="wechat-1",
        participant_actor_id="participant-buyer-1",
        participant_role_context="buyer",
        participant_conversation_role="buyer_thread",
        authorization_basis="tenant_api_key",
        production=True,
    )
    values.update(overrides)
    return RequestContext(**values)


def _event(**overrides):
    event = {
        "channel": "wechat",
        "conversation_id": "conv-1",
        "sender_id": "body-sender",
        "message_text": "Need a quote",
    }
    event.update(overrides)
    return event


def test_trusted_headers_generate_canonical_separate_identity_fields():
    event = apply_trusted_identity(_event(role_context="customer"), _context())
    assert event["actor_id"] == "participant-buyer-1"
    assert event["authenticated_actor_id"] == "actor-1"
    assert event["authenticated_actor_role"] == "buyer"
    assert event["business_role"] == "buyer"
    assert event["role_context"] == "buyer"
    assert event["conversation_role"] == "buyer_thread"
    assert event["execution_mode"] == "auto"
    assert event["authorization_basis"] == "tenant_api_key"


def test_production_requires_trusted_actor_id():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(_event(), _context(actor_id=""))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "ACTOR_ID_REQUIRED"


def test_production_requires_trusted_business_role():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(_event(), _context(role_context="", conversation_role=""))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "ACTOR_ROLE_REQUIRED"


def test_production_requires_asserted_participant_identity():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(_event(), _context(participant_actor_id=""))
    assert exc.value.detail["error"] == "PARTICIPANT_ID_REQUIRED"


def test_production_requires_asserted_participant_role():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(_event(), _context(participant_role_context=""))
    assert exc.value.detail["error"] == "PARTICIPANT_ROLE_REQUIRED"


def test_production_rejects_body_conversation_role():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(
            _event(conversation_role="supplier_thread"),
            _context(participant_conversation_role=""),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "UNTRUSTED_CONVERSATION_ROLE"


def test_trusted_role_cannot_enter_another_participant_thread():
    with pytest.raises(HTTPException) as exc:
        apply_trusted_identity(
            _event(),
            _context(participant_role_context="supplier", participant_conversation_role="buyer_thread"),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "CONVERSATION_ROLE_MISMATCH"


def test_local_legacy_alias_is_normalized_without_granting_admin():
    context = _context(
        actor_id="",
        role_context="",
        conversation_role="",
        execution_mode="",
        authorization_basis="local_compatibility",
        production=False,
        participant_actor_id="",
        participant_role_context="",
        participant_conversation_role="",
    )
    event = apply_trusted_identity(
        _event(role_context="operator", mode="command"), context
    )
    assert event["actor_id"] == "body-sender"
    assert event["sender_id"] == "body-sender"
    assert event["business_role"] == "sales"
    assert event["conversation_role"] == "internal_thread"
    assert event["execution_mode"] == "command"
    assert event["authenticated_actor_id"] == "body-sender"
    assert event["authenticated_actor_role"] == "operator"


def test_local_explicit_actor_remains_compatible_without_promoting_sender():
    context = _context(
        actor_id="",
        role_context="",
        conversation_role="",
        execution_mode="",
        authorization_basis="local_compatibility",
        production=False,
        participant_actor_id="",
        participant_role_context="",
        participant_conversation_role="",
    )
    explicit = apply_trusted_identity(
        _event(actor_id="local-user", role_context="operator", mode="command"), context
    )
    assert explicit["authenticated_actor_id"] == "local-user"
    assert explicit["authenticated_actor_role"] == "operator"

