from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from aivan.db.models.project import Project
from aivan.db.models.supplier import SupplierRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.execution import (
    EventReversalRecord,
    ExecutionEventRecord,
    ProcessedInboundEvent,
)
from aivan.db.models.platform import PlatformRecord
from aivan.db.models.account import OpenClawAccountRecord
from aivan.db.models.preference import UserPreferenceRecord
from aivan.db.models.relay import RelayReceiptRecord
from aivan.db.models.migration import SchemaMigrationRecord
from aivan.db.models.domain import (
    ApprovalRecord,
    AuditLogRecord,
    CaseConversationRecord,
    CaseMessageRecord,
    CaseParticipantRecord,
)

__all__ = [
    "Base",
    "Project",
    "SupplierRecord",
    "InquiryDraftRecord",
    "ExecutionEventRecord",
    "EventReversalRecord",
    "ProcessedInboundEvent",
    "PlatformRecord",
    "OpenClawAccountRecord",
    "UserPreferenceRecord",
    "RelayReceiptRecord",
    "SchemaMigrationRecord",
    "ApprovalRecord",
    "AuditLogRecord",
    "CaseConversationRecord",
    "CaseMessageRecord",
    "CaseParticipantRecord",
]
