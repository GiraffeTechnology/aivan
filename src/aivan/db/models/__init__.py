from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from aivan.db.models.project import Project
from aivan.db.models.supplier import SupplierRecord
from aivan.db.models.inquiry import InquiryDraftRecord
from aivan.db.models.execution import ExecutionEventRecord
from aivan.db.models.platform import PlatformRecord
from aivan.db.models.account import OpenClawAccountRecord
from aivan.db.models.inbound_event import InboundRelayEvent

__all__ = [
    "Base",
    "Project",
    "SupplierRecord",
    "InquiryDraftRecord",
    "ExecutionEventRecord",
    "PlatformRecord",
    "OpenClawAccountRecord",
    "InboundRelayEvent",
]
