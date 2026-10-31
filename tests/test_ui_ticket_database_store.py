"""Portable control-store tests, not MySQL/runtime deployment acceptance."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session


def _database(tmp_path):
    from scripts.migrate_ui_ticket_receipts import apply

    url = f"sqlite:///{tmp_path / 'control.sqlite3'}"
    apply(url)
    return create_engine(url, connect_args={"check_same_thread": False})


def test_ticket_store_plan_does_not_create_table(tmp_path):
    from scripts.migrate_ui_ticket_receipts import plan

    url = f"sqlite:///{tmp_path / 'empty.sqlite3'}"
    result = plan(url)
    assert result["table_required"] is True
    engine = create_engine(url)
    assert "ui_test_ticket_receipts" not in inspect(engine).get_table_names()
    engine.dispose()


def test_ticket_store_atomic_consumption_and_restart(tmp_path):
    from aivan.api.ticket_store import consume_ticket_digest
    from aivan.db.models.ui_ticket import UITestTicketReceipt

    engine = _database(tmp_path)
    digest = "a" * 64
    with Session(engine) as session:
        consume_ticket_digest(session, digest, expires_at=200, current=100)
    engine.dispose()
    engine = create_engine(f"sqlite:///{tmp_path / 'control.sqlite3'}")
    with Session(engine) as session:
        with pytest.raises(ValueError, match="already consumed"):
            consume_ticket_digest(session, digest, expires_at=200, current=101)
        row = session.get(UITestTicketReceipt, digest)
        assert row is not None and row.expires_at == 200
        assert set(row.__table__.columns.keys()) == {"digest", "expires_at", "consumed_at"}
    engine.dispose()


def test_ticket_store_concurrent_claim_has_one_winner(tmp_path):
    from aivan.api.ticket_store import consume_ticket_digest
    from aivan.db.models.ui_ticket import UITestTicketReceipt

    engine = _database(tmp_path)
    barrier = threading.Barrier(2)

    def claim():
        with Session(engine) as session:
            barrier.wait(timeout=5)
            try:
                consume_ticket_digest(session, "b" * 64, expires_at=200, current=100)
                return "consumed"
            except ValueError:
                return "replay"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(outcomes) == ["consumed", "replay"]
    with Session(engine) as session:
        assert len(session.scalars(select(UITestTicketReceipt)).all()) == 1
    engine.dispose()


def test_ticket_store_failure_does_not_create_schema(tmp_path):
    from aivan.api.ticket_store import TicketStoreUnavailable, consume_ticket_digest

    engine = create_engine(f"sqlite:///{tmp_path / 'unmigrated.sqlite3'}")
    with Session(engine) as session:
        with pytest.raises(TicketStoreUnavailable):
            consume_ticket_digest(session, "c" * 64, expires_at=200, current=100)
    assert "ui_test_ticket_receipts" not in inspect(engine).get_table_names()
    engine.dispose()


def test_production_ticket_store_requires_request_database(monkeypatch, tmp_path):
    from aivan.api.session_auth import validate_test_ticket_configuration

    path = tmp_path / "must-not-create.sqlite3"
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_UI_TEST_TICKET_SECRET", "s" * 48)
    monkeypatch.setenv("AIVAN_UI_TEST_TICKET_LEDGER_PATH", str(path))
    with pytest.raises(ValueError, match="database session"):
        validate_test_ticket_configuration()
    assert not path.exists()


def test_ticket_store_uses_configured_database_not_legacy_path(monkeypatch, tmp_path):
    from aivan.api.session_auth import consume_test_login_ticket, issue_test_login_ticket

    engine = _database(tmp_path)
    path = tmp_path / "must-not-create.sqlite3"
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_UI_TEST_TICKET_SECRET", "s" * 48)
    monkeypatch.setenv("AIVAN_UI_TEST_TICKET_LEDGER_PATH", str(path))
    ticket = issue_test_login_ticket(now=100, ttl_seconds=100)
    with Session(engine) as session:
        reference = consume_test_login_ticket(ticket, now=101, db=session)
        assert len(reference) == 16
        with pytest.raises(ValueError, match="invalid test login ticket"):
            consume_test_login_ticket(ticket, now=102, db=session)
    assert not path.exists()
    engine.dispose()


def test_ticket_store_mysql_and_postgresql_ddl_are_portable():
    from sqlalchemy.dialects import mysql, postgresql
    from sqlalchemy.schema import CreateTable
    from aivan.db.models.ui_ticket import UITestTicketReceipt

    # Compilation is not a claim of a live MySQL/PostgreSQL execution.
    for dialect in (mysql.dialect(), postgresql.dialect()):
        ddl = str(CreateTable(UITestTicketReceipt.__table__).compile(dialect=dialect))
        assert "PRIMARY KEY" in ddl and "digest" in ddl
        assert "sqlite" not in ddl.lower()
