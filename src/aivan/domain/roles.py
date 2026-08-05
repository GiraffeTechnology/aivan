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
    BusinessRole.QC: frozenset({Capability.EwßÏ8¶‰ËkºwµçUÙ•ÉÍ”ˆ°(€€€€€€€¡•…‘•ÉÌõ}¡•…‘•ÉÌ¡¥‘•µÁ½Ñ•¹å}­•äô‰É•Ù•ÉÍ”µÍÑÉ…Ñ•äˆ¤°(€€€€€€€©Í½¸õì‰É•…Í½¸ˆè€‰I•ÍÑ½É”Ñ¡”…ÁÁÉ½Ù•½ÍĞÍÑÉ…Ñ•ä¸‰ô°(€€€€¤(€€€…ÍÍ•ÉĞÉ•ÍÁ½¹Í”¹ÍÑ…ÑÕÍ}½‘”€ôô€ÈÀÀ(€€€…ÍÍ•ÉĞÁÉ½©•Ğ¹É•ÅÕ¥É•µ•¹Ñ}©Í½¹l‰ÍÑÉ…Ñ•ä‰t€ôôì‰ÁÉ¥½É¥Ñäˆè€‰½ÍĞ‰ô(()‘•˜Ñ•ÍÑ}•Ù•¹Ñ}…ÁÁ•¹‘}Á•ÉÍ¥ÍÑÍ}ÍÑ…‰±•}Á…å±½…‘}‘¥•ÍĞ¡½ÉÉ•Ñ¥½¹}…Á¤¤è(€€€}±¥•¹Ğ°‘ˆ€ô½ÉÉ•Ñ¥½¹}…Á¤(€€€ÁÉ½©•Ğ€ôAÉ½©•ÑI•Á½Í¥Ñ½Éä¡‘ˆ¤¹É•…Ñ” (€€€€€€€€‰‘¥•ÍĞµ½¹Ù•ÉÍ…Ñ¥½¸ˆ°€‰‰Õå•Èµ‘¥•ÍĞˆ°Ñ•¹…¹Ñ}¥ô‰Ñ•¹…¹Ğµ„ˆ(€€€€¤(€€€™¥ÉÍĞ€ôá•ÕÑ¥½¹Ù•¹ÑI•Á½Í¥Ñ½Éä¡‘ˆ¤¹…ÁÁ•¹ (€€€€€€€ÁÉ½©•Ğ¹ÁÉ½©•Ñ}¥°(€€€€€€€€‰%MQ}QMPˆ°(€€€€€€€€‰MÑ…‰±”•Ù¥‘•¹”ˆ°(€€€€€€€Ñ•¹…¹Ñ}¥ô‰Ñ•¹…¹Ğµ„ˆ°(€€€€€€€Á…å±½…õì‰ˆˆè€È°€‰„ˆè€Åô°(€€€€€€€‰•™½É”õì‰Ù…±Õ”ˆè€Åô°(€€€€€€€…™Ñ•Èõì‰Ù…±Õ”ˆè€Éô°(€€€€¤(€€€Í•½¹€ôá•ÕÑ¥½¹Ù•¹ÑI•Á½Í¥Ñ½Éä¡‘ˆ¤¹…ÁÁ•¹ (€€€€€€€ÁÉ½©•Ğ¹ÁÉ½©•Ñ}¥°(€€€€€€€€‰%MQ}QMPˆ°(€€€€€€€€‰MÑ…‰±”•Ù¥‘•¹”ˆ°(€€€€€€€Ñ•¹…¹Ñ}¥ô‰Ñ•¹…¹Ğµ„ˆ°(€€€€€€€Á…å±½…õì‰„ˆè€Ä°€‰ˆˆè€Éô°(€€€€€€€‰•™½É”õì‰Ù…±Õ”ˆè€Åô°(€€€€€€€…™Ñ•Èõì‰Ù…±Õ”ˆè€Éô°(€€€€¤(€€€…ÍÍ•ÉĞ±•¸¡™¥ÉÍĞ¹Á…å±½…‘}‘¥•ÍĞ¤€ôô€ØĞ(€€€…ÍÍ•ÉĞ™¥ÉÍĞ¹Á…å±½…‘}‘¥•ÍĞ€ôôÍ•½¹¹Á…å±½…‘}‘¥•ÍĞ(