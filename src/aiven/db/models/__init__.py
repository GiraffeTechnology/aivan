from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

from aiven.db.models.project import Project
from aiven.db.models.supplier import SupplierRecord
from aiven.db.models.inquiry import InquiryDraftRecord
from aiven.db.models.execution import ExecutionEventRecord
from aiven.db.models.platform import PlatformRecord
from aiven.db.models.account import OpenClawAccountRecord

__all__ = [
    "Base",
    "Project",
    "SupplierRecord",
    "InquiryDraftRecord",
    "ExecutionEventRecord",
    "PlatformRecord",
    "OpenClawAccountRecord",
]
