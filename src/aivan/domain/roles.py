"""Canonical Stage 2 role, capability, and case-transition policy.

Identity fields are deliberately separate:

* ``actor_id`` identifies the authenticated person/service.
* ``business_role`` grants business capabilities.
* ``conversation_role`` identifies the participant thread being used.
* ``execution_mode`` describes how the action was requested.

Legacy ``role_context`` aliases are accepted only at the boundary and are
immediately normalized to :class:`BusinessRole`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class BusinessRole(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"
    SALES = "sales"
    PROCUREMENT = "procurement"
    FOLLOW_UP = "follow_up"
    QC = "qc"
    LOGISTICS = "logistics"
    ADMIN = "admin"
    APPROVER = "approver"
    AUDITOR = "auditor"


class ConversationRole(StrEnum):
    BUYER_THREAD = "buyer_thread"
    SUPPLIER_THREAD = "supplier_thread"
    INTERNAL_THREAD = "internal_thread"
    APPROVAL_THREAD = "approval_thread"
    QC_THREAD = "qc_thread"
    LOGISTICS_THREAD = "logistics_thread"
    AUDIT_THREAD = "audit_thread"


class ExecutionMode(StrEnum):
    AUTO = "auto"
    COMMAND = "command"
    APPROVAL = "approval"
    UPDATE = "update"
    AUDIT = "audit"


class Capability(StrEnum):
    CREATE_INQUIRY = "create_inquiry"
    RESPOND_AS_SUPPLIER = "respond_as_supplier"
    EXECUTE_COMMAND = "execute_command"
    UPDATE_STRATEGY = "update_strategy"
    SELECT_SUPPLIER = "select_supplier"
    APPROVE_OUTBOUND = "approve_outbound"
    SEND_OUTBOUND = "send_outbound"
    COMMIT_LEAD_TIME = "commit_lead_time"
    UPDATE_QC = "update_qc"
    UPDATE_LOGISTICS = "update_logistics"
    VIEW_AUDIT = "view_audit"
    REVERSE_EVENT = "reverse_event"


class CaseState(StrEnum):
    INQUIRY = "inquiry"
    SOURCING = "sourcing"
    AWAITING_SUPPLIER = "awaiting_supplier"
    SUPPLIER_REPLIED = "supplier_replied"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    QC = "qc"
    LOGISTICS = "logistics"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ROLE_ALIASES: dict[str, BusinessRole] = {
    "buyer": BusinessRole.BUYER,
    "customer": BusinessRole.BUYER,
    "b_side": BusinessRole.BUYER,
    "supplier": BusinessRole.SUPPLIER,
    "seller": BusinessRole.SUPPLIER,
    "m_side": BusinessRole.SUPPLIER,
    "sales": BusinessRole.SALES,
    "salesperson": BusinessRole.SALES,
    "user": BusinessRole.SALES,
    "owner": BusinessRole.SALES,
    "operator": BusinessRole.SALES,
    "procurement": BusinessRole.PROCUREMENT,
    "purchasing": BusinessRole.PROCUREMENT,
    "follow_up": BusinessRole.FOLLOW_UP,
    "follow-up": BusinessRole.FOLLOW_UP,
    "merchandiser": BusinessRole.FOLLOW_UP,
    "qc": BusinessRole.QC,
    "quality": BusinessRole.QC,
    "logistics": BusinessRole.LOGISTICS,
    "shipping": BusinessRole.LOGISTICS,
    "admin": BusinessRole.ADMIN,
    "administrator": BusinessRole.ADMIN,
    "approver": BusinessRole.APPROVER,
    "auditor": BusinessRole.AUDITOR,
    "audit": BusinessRole.AUDITOR,
}

MODE_ALIASES: dict[str, ExecutionMode] = {
    "": ExecutionMode.AUTO,
    "auto": ExecutionMode.AUTO,
    "automatic": ExecutionMode.AUTO,
    "user": ExecutionMode.COMMAND,
    "command": ExecutionMode.COMMAND,
    "approval": ExecutionMode.APPROVAL,
    "approve": ExecutionMode.APPROVAL,
    "update": ExecutionMode.UPDATE,
    "audit": ExecutionMode.AUDIT,
}

DEFAULT_CONVERSATION_ROLE: dict[BusinessRole, ConversationRole] = {
    BusinessRole.BUYER: ConversationRole.BUYER_THREAD,
    BusinessRole.SUPPLIER: ConversationRole.SUPPLIER_THREAD,
    BusinessRole.SALES: ConversationRole.INTERNAL_THREAD,
    BusinessRole.PROCUREMENT: ConversationRole.INTERNAL_THREAD,
    BusinessRole.FOLLOW_UP: ConversationRole.INTERNAL_THREAD,
    BusinessRole.QC: ConversationRole.QC_THREAD,
    BusinessRole.LOGISTICS: ConversationRole.LOGISTICS_THREAD,
    BusinessRole.ADMIN: ConversationRole.INTERNAL_THREAD,
    BusinessRole.APPROVER: ConversationRole.APPROVAL_THREAD,
    BusinessRole.AUDITOR: ConversationRole.AUDIT_THREAD,
}

ROLE_CAPABILITIES: dict[BusinessRole, frozenset[Capability]] = {
    BusinessRole.BUYER: frozenset({Capability.CREATE_INQUIRY}),
    BusinessRole.SUPPLIER: frozenset({Capability.RESPOND_AS_SUPPLIER}),
    BusinessRole.SALES: frozenset(
        {Capability.CREATE_INQUIRY, Capability.EXECUTE_COMMAND, Capability.UPDATE_STRATEGY}
    ),
    BusinessRole.PROCUREMENT: frozenset(
        {Capability.EXECUTE_COMMAND, Capability.UPDATE_STRATEGY, Capability.SELECT_SUPPLIER}
    ),
    BusinessRole.FOLLOW_UP: frozenset(
        {Capability.EXECUTE_COMMAND, Capability.UPDATE_LOGISTICS}
    ),
    BusinessRole.QC: frozenset({Capability.EXECUTE_COMMAND, Capability.UPDATE_QC}),
    BusinessRole.LOGISTICS: frozenset(
        {Capability.EXECUTE_COMMAND, Capability.UPDATE_LOGISTICS}
    ),
    BusinessRole.APPROVER: frozenset(
        {
            Capability.EXECUTE_COMMAND,
            Capability.APPROVE_OUTBOUND,
            Capability.SEND_OUTBOUND,
            Capability.COMMIT_LEAD_TIME,
        }
    ),
    BusinessRole.AUDITOR: frozenset({Capability.VIEW_AUDIT}),
    BusinessRole.ADMIN: frozenset(Capability),
}


class RoleAuthorizationError(RuntimeError):
    """Typed fail-closed role or transition rejection."""

    def __init__(self, code: str, message: str, *, reason: str = ""):
        super().__init__(message)
        self.code = code
        self.reason = reason or message


@dataclass(frozen=True)
class ActorIdentity:
    actor_id: str
    business_role: BusinessRole
    conversation_role: ConversationRole
    execution_mode: ExecutionMode
    authorization_basis: str

    def as_audit_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class TransitionDecision:
    before: CaseState
    after: CaseState
    actor_id: str
    actor_role: BusinessRole
    capability: Capability
    authorization_basis: str

    def as_audit_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


TRANSITIONS: dict[tuple[CaseState, CaseState], Capability] = {
    (CaseState.INQUIRY, CaseState.SOURCING): Capability.UPDATE_STRATEGY,
    (CaseState.SOURCING, CaseState.AWAITING_SUPPLIER): Capability.SELECT_SUPPLIER,
    (CaseState.AWAITING_SUPPLIER, CaseState.SUPPLIER_REPLIED): Capability.RESPOND_AS_SUPPLIER,
    (CaseState.SUPPLIER_REPLIED, CaseState.AWAITING_APPROVAL): Capability.UPDATE_STRATEGY,
    (CaseState.AWAITING_APPROVAL, CaseState.APPROVED): Capability.APPROVE_OUTBOUND,
    (CaseState.APPROVED, CaseState.QC): Capability.UPDATE_QC,
    (CaseState.QC, CaseState.LOGISTICS): Capability.UPDATE_LOGISTICS,
    (CaseState.LOGISTICS, CaseState.COMPLETED): Capability.COMMIT_LEAD_TIME,
}


def normalize_business_role(value: str | BusinessRole | None, *, mode: str = "auto") -> BusinessRole:
    if isinstance(value, BusinessRole):
        return value
    normalized = (value or "").strip().lower()
    if normalized:
        role = ROLE_ALIASES.get(normalized)
        if role is None:
            raise RoleAuthorizationError(
                "INVALID_BUSINESS_ROLE",
                f"Unsupported business role: {normalized}",
                reason="role_not_in_canonical_enum",
            )
        return role
    execution_mode = normalize_execution_mode(mode)
    return BusinessRole.SALES if execution_mode == ExecutionMode.COMMAND else BusinessRole.BUYER


def normalize_execution_mode(value: str | ExecutionMode | None) -> ExecutionMode:
    if isinstance(value, ExecutionMode):
        return value
    normalized = (value or "").strip().lower()
    mode = MODE_ALIASES.get(normalized)
    if mode is None:
        raise RoleAuthorizationError(
            "INVALID_EXECUTION_MODE",
            f"Unsupported execution mode: {normalized}",
            reason="mode_not_in_canonical_enum",
        )
    return mode


def normalize_conversation_role(
    value: str | ConversationRole | None, business_role: BusinessRole
) -> ConversationRole:
    if isinstance(value, ConversationRole):
        result = value
    elif value and value.strip():
        try:
            result = ConversationRole(value.strip().lower())
        except ValueError as exc:
            raise RoleAuthorizationError(
                "INVALID_CONVERSATION_ROLE",
                f"Unsupported conversation role: {value}",
                reason="conversation_role_not_in_enum",
            ) from exc
    else:
        result = DEFAULT_CONVERSATION_ROLE[business_role]
    allowed = DEFAULT_CONVERSATION_ROLE[business_role]
    if result != allowed and business_role != BusinessRole.ADMIN:
        raise RoleAuthorizationError(
            "CONVERSATION_ROLE_MISMATCH",
            f"{business_role} cannot act in {result}",
            reason=f"expected_{allowed}",
        )
    return result


def normalize_actor_identity(
    *,
    actor_id: str,
    business_role: str | BusinessRole | None,
    conversation_role: str | ConversationRole | None = None,
    execution_mode: str | ExecutionMode | None = None,
    authorization_basis: str,
) -> ActorIdentity:
    mode = normalize_execution_mode(execution_mode)
    role = normalize_business_role(business_role, mode=mode)
    return ActorIdentity(
        actor_id=(actor_id or "").strip(),
        business_role=role,
        conversation_role=normalize_conversation_role(conversation_role, role),
        execution_mode=mode,
        authorization_basis=(authorization_basis or "").strip(),
    )


def require_capability(identity: ActorIdentity, capability: Capability) -> None:
    if not identity.actor_id:
        raise RoleAuthorizationError(
            "ACTOR_ID_REQUIRED",
            "Authenticated actor identity is required",
            reason="missing_actor_id",
        )
    if capability not in ROLE_CAPABILITIES[identity.business_role]:
        raise RoleAuthorizationError(
            "CAPABILITY_FORBIDDEN",
            f"Role {identity.business_role} cannot perform {capability}",
            reason=f"role_{identity.business_role}_lacks_{capability}",
        )


def authorize_transition(
    before: CaseState | str,
    after: CaseState | str,
    identity: ActorIdentity,
) -> TransitionDecision:
    before_state = CaseState(before)
    after_state = CaseState(after)
    capability = TRANSITIONS.get((before_state, after_state))
    if capability is None:
        raise RoleAuthorizationError(
            "INVALID_CASE_TRANSITION",
            f"Transition {before_state} -> {after_state} is not allowed",
            reason="transition_not_in_state_machine",
        )
    require_capability(identity, capability)
    return TransitionDecision(
        before=before_state,
        after=after_state,
        actor_id=identity.actor_id,
        actor_role=identity.business_role,
        capability=capability,
        authorization_basis=identity.authorization_basis,
    )
