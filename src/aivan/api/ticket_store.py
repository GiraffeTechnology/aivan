"""DB-neutral atomic test-ticket receipts; no implicit file or memory fallback."""
from __future__ import annotations

import logging
import re

from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from aivan.db.models.ui_ticket import UITestTicketReceipt
from aivan.observability.safe_logging import log_exception_safely

logger = logging.getLogger(__name__)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class TicketStoreUnavailable(RuntimeError):
    """No authentication success may be inferred from an unavailable store."""


def validate_ticket_store(db: Session) -> None:
    """Read schema capabilities without creating or migrating anything."""
    try:
        schema = inspect(db.get_bind())
        name = UITestTicketReceipt.__tablename__
        if not schema.has_table(name):
            raise ValueError("test ticket database migration is required")
        columns = {column["name"] for column in schema.get_columns(name)}
        primary = set(schema.get_pk_constraint(name).get("constrained_columns") or [])
        if not {"digest", "expires_at", "consumed_at"} <= columns or primary != {"digest"}:
            raise ValueError("test ticket database schema is incompatible")
    except SQLAlchemyError as exc:
        log_exception_safely(logger, "UI ticket database validation failed", exc=exc)
        raise ValueError("test ticket database is unavailable") from None


def consume_ticket_digest(db: Session, digest: str, *, expires_at: int, current: int) -> None:
    """Commit one unique digest before session issuance, across workers/restarts."""
    if not _DIGEST.fullmatch(digest) or expires_at <= current or current < 0:
        raise ValueError("invalid test ticket receipt")
    # The login handler supplies a read-only control session. Never commit an
    # unrelated caller's staged business changes as part of authentication.
    if db.new or db.dirty or db.deleted:
        raise TicketStoreUnavailable("UI_TEST_TICKET_STORE_UNAVAILABLE")
    try:
        db.execute(delete(UITestTicketReceipt).where(UITestTicketReceipt.expires_at <= current))
        db.add(UITestTicketReceipt(digest=digest, expires_at=expires_at, consumed_at=current))
        db.commit()
        # A successful commit acknowledgement is followed by authoritative
        # readback. A missing/failed readback cannot issue a login session.
        receipt = db.get(UITestTicketReceipt, digest, populate_existing=True)
        if receipt is None or receipt.expires_at != expires_at or receipt.consumed_at != current:
            raise TicketStoreUnavailable("UI_TEST_TICKET_STORE_UNAVAILABLE")
    except IntegrityError:
        db.rollback()
        raise ValueError("test login ticket already consumed") from None
    except SQLAlchemyError as exc:
        db.rollback()
        log_exception_safely(logger, "UI ticket consume failed", exc=exc)
        # A lost commit acknowledgement is not permission to issue a session
        # or replay the ticket. A later request is checked by the same PK.
        raise TicketStoreUnavailable("UI_TEST_TICKET_STORE_UNAVAILABLE") from None
