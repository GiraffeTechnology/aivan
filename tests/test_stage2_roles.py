"""Stage 2 canonical role, RBAC, and transition policy tests."""
from __future__ import annotations

import pytest

from aivan.domain.roles import (
    BusinessRole,
    Capability,
    CaseState,
    ConversationRole,
    ExecutionMode,
    RoleAuthorizationError,
    authorize_transition,
    normalize_actor_identity,
    normalize_business_role,
    require_capability,
)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("buyer", BusinessRole.BUYER),
        ("customer", BusinessRole.BUYER),
        ("b_side", BusinessRole.BUYER),
        ("supplier", BusinessRole.SUPPLIER),
        ("seller", BusinessRole.SUPPLIER),
        ("m_side", BusinessRole.SUPPLIER),
        ("operator", BusinessRole.SALES),
        ("merchandiser", BusinessRole.FOLLOW_UP),
    ],
)
def test_legacy_aliases_normalize_at_boundary(alias, expected):
    assert normalize_business_role(alias) == expected


def test_identity_dimensions_are_separate_and_auditable():
    identity = normalize_actor_identity(
        actor_id="actor-42",
        business_role="approver",
        conversation_role="approval_thread",
        execution_mode="approval",
        authorization_basis="trusted_gateway_header",
    )
    assert identity.business_role == BusinessRole.APPROVER
    assert identity.conversation_role == ConversationRole.APPROVAL_THREAD
    assert identity.execution_mode == ExecutionMode.APPROVAL
    assert identity.as_audit_dict()["actor_id"] == "actor-42"


def test_unknown_role_fails_closed():
    with pytest.raises(RoleAuthorizationError) as exc:
        normalize_business_role("superuser")
    assert exc.value.code == "INVALID_BUSINESS_ROLE"


def test_conversation_role_cannot_impersonate_other_thread():
    with pytest.raises(RoleAuthorizationError) as exc:
        normalize_actor_identity(
            actor_id="supplier-1",
            business_role="supplier",
            conversation_role="buyer_thread",
            execution_mode="auto",
            authorization_basis="channel_binding",
        )
    assert exc.value.code == "CONVERSATION_ROLE_MISMATCH"


@pytest.mark.parametrize("role", ["buyer", "supplier", "sales", "procurement", "qc", "logistics", "auditor"])
def test_only_approver_or_admin_can_approve_and_send(role):
    identity = normalize_actor_identity(
        actor_id=f"{role}-1",
        business_role=role,
        execution_mode="command",
        authorization_basis="test_binding",
    )
    for capability in (Capability.APPROVE_OUTBOUND, Capability.SEND_OUTBOUND):
        with pytest.raises(RoleAuthorizationError) as exc:
            require_capability(identity, capability)
        assert exc.value.code == "CAPABILITY_FORBIDDEN"


@pytest.mark.parametrize("role", ["approver", "admin"])
def test_approver_and_admin_can_approve_and_send(role):
    identity = normalize_actor_identity(
        actor_id=f"{role}-1",
        business_role=role,
        execution_mode="approval",
        authorization_basis="test_binding",
    )
    require_capability(identity, Capability.APPROVE_OUTBOUND)
    require_capability(identity, Capability.SEND_OUTBOUND)


def test_supplier_reply_transition_keeps_actor_and_authorization_basis():
    supplier = normalize_actor_identity(
        actor_id="supplier-1",
        business_role="supplier",
        execution_mode="auto",
        authorization_basis="verified_channel_participant",
    )
    decision = authorize_transition(
        CaseState.AWAITING_SUPPLIER, CaseState.SUPPLIER_REPLIED, supplier
    )
    evidence = decision.as_audit_dict()
    assert evidence["before"] == "awaiting_supplier"
    assert evidence["after"] == "supplier_replied"
    assert evidence["actor_id"] == "supplier-1"
    assert evidence["actor_role"] == "supplier"
    assert evidence["authorization_basis"] == "verified_channel_participant"


def test_buyer_cannot_fake_supplier_transition():
    buyer = normalize_actor_identity(
        actor_id="buyer-1",
        business_role="buyer",
        execution_mode="auto",
        authorization_basis="verified_channel_participant",
    )
    with pytest.raises(RoleAuthorizationError) as exc:
        authorize_transition(
            CaseState.AWAITING_SUPPLIER, CaseState.SUPPLIER_REPLIED, buyer
        )
    assert exc.value.code == "CAPABILITY_FORBIDDEN"


def test_invalid_state_jump_is_rejected_even_for_admin():
    admin = normalize_actor_identity(
        actor_id="admin-1",
        business_role="admin",
        execution_mode="command",
        authorization_basis="admin_session",
    )
    with pytest.raises(RoleAuthorizationError) as exc:
        authorize_transition(CaseState.INQUIRY, CaseState.COMPLETED, admin)
    assert exc.value.code == "INVALID_CASE_TRANSITION"
