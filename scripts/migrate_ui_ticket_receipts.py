"""Preview/apply the portable UI authentication-receipt table migration."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect

from aivan.db.models.ui_ticket import UITestTicketReceipt


def plan(database_url: str) -> dict:
    engine = create_engine(database_url)
    try:
        return {
            "table": UITestTicketReceipt.__tablename__,
            "table_required": not inspect(engine).has_table(UITestTicketReceipt.__tablename__),
        }
    finally:
        engine.dispose()


def apply(database_url: str) -> dict:
    engine = create_engine(database_url)
    try:
        existed = inspect(engine).has_table(UITestTicketReceipt.__tablename__)
        # A targeted migration, not an implicit startup create_all().
        UITestTicketReceipt.__table__.create(engine, checkfirst=True)
        return {"table": UITestTicketReceipt.__tablename__, "created": not existed}
    finally:
        engine.dispose()
