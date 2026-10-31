"""Hashed, single-use UI authentication receipts in the configured control DB."""
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from aivan.db.models import Base


class UITestTicketReceipt(Base):
    __tablename__ = "ui_test_ticket_receipts"

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
