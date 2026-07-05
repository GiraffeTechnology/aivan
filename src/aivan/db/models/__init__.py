from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from aivan.db.models.project import Project
from aivan.db.models.supplier import SupplierRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.execution import ExecutionEventRecord, ProcessedInboundEvent
from aivan.db.models.platform import PlatformRecord
from aivan.db.models.account import OpenClawAccountRecord
from aivan.db.models.preference import UserPreferenceRecord
from aivan.db.models.web_case import (
    WebAttachmentRecord,
    WebAuditLogRecord,
    WebCaseMessageRecord,
    WebCaseRecord,
    WebOutboundDraftRecord,
)

__all__ = [
    "Base",
    "Project",
    "SupplierRecord",
    "InquiryDraftRecord",
    "ExecutionEventRecord",
    "ProcessedInboundEvent",
    "PlatformRecord",
    "OpenClawAccountRecord",
    "UserPreferenceRecord",
    "WebCaseRecord",
    "WebCaseMessageRecord",
    "WebOutboundDraftRecord",
    "WebAttachmentRecord",
    "WebAuditLogRecord",
]
