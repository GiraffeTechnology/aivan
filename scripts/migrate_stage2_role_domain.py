"""Add the Stage 2 multi-role Case domain to an existing AIVAN database.

The migration is additive and deliberately opt-in. By default it only prints a
plan. Pass ``--apply`` after taking a backup and verifying the target database.
It never drops tables, columns, indexes, or existing records.
"""
from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, inspect, text

from aivan.db.models import Base  # imports and registers all Stage 2 models


NEW_TABLES = (
    "case_conversations",
    "case_participants",
    "case_messages",
    "approvals",
    "audit_logs",
)

# SQL is static: neither identifiers nor defaults are supplied by the operator.
# JSON columns are nullable during upgrade for MySQL compatibility; new databases
# receive the stricter ORM definition through metadata.create_all().
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "projects": {
        "case_state": "VARCHAR(64) NOT NULL DEFAULT 'inquiry'",
        "source_trace_id": "VARCHAR(255) NOT NULL DEFAULT ''",
    },
    "inquiry_drafts": {
        "participant_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "source_trace_id": "VARCHAR(255) NOT NULL DEFAULT ''",
        "created_by_actor_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "created_by_actor_role": "VARCHAR(64) NOT NULL DEFAULT ''",
        "approval_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "authorization_basis": "TEXT",
    },
    "execution_events": {
        "tenant_id": "VARCHAR(128) NOT NULL DEFAULT 'legacy'",
        "source_trace_id": "VARCHAR(255) NOT NULL DEFAULT ''",
        "actor_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "actor_role": "VARCHAR(64) NOT NULL DEFAULT ''",
        "conversation_role": "VARCHAR(64) NOT NULL DEFAULT ''",
        "authorization_basis": "TEXT",
        "before_json": "JSON",
        "after_json": "JSON",
        "rejection_reason": "TEXT",
    },
    "openclaw_accounts": {
        "tenant_id": "VARCHAR(128) NOT NULL DEFAULT 'legacy'",
    },
    "user_preferences": {
        "tenant_id": "VARCHAR(128) NOT NULL DEFAULT 'legacy'",
    },
    "suppliers": {
        "tenant_id": "VARCHAR(128) NOT NULL DEFAULT 'legacy'",
    },
    "platforms": {
        "tenant_id": "VARCHAR(128) NOT NULL DEFAULT 'legacy'",
    },
    "case_messages": {
        "asserted_by_actor_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "asserted_by_actor_role": "VARCHAR(64) NOT NULL DEFAULT ''",
    },
}

INDEXED_COLUMNS: dict[str, tuple[str, ...]] = {
    "projects": ("case_state", "source_trace_id"),
    "inquiry_drafts": ("participant_id", "source_trace_id", "approval_id"),
    "execution_events": ("tenant_id", "source_trace_id", "actor_id"),
    "openclaw_accounts": ("tenant_id",),
    "user_preferences": ("tenant_id",),
    "suppliers": ("tenant_id",),
    "platforms": ("tenant_id",),
    "case_messages": ("asserted_by_actor_id", "asserted_by_actor_role"),
}


def _database_url() -> str:
    return os.environ.get("AIVAN_DB_URL", "sqlite:///./data/aiven.db")


def plan(database_url: str) -> list[tuple[str, str, str]]:
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        tables = set(schema.get_table_names())
        changes: list[tuple[str, str, str]] = []
        for table in NEW_TABLES:
            changes.append(
                (table, "table", "already_exists" if table in tables else "create")
            )
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in tables:
                changes.append((table, "table", "skip_missing_legacy_table"))
                continue
            existing = {column["name"] for column in schema.get_columns(table)}
            for column in columns:
                changes.append(
                    (table, column, "already_exists" if column in existing else "add")
                )
        return changes
    finally:
        engine.dispose()


def apply(database_url: str) -> list[tuple[str, str, str]]:
    engine = create_engine(database_url)
    applied: list[tuple[str, str, str]] = []
    try:
        quote = engine.dialect.identifier_preparer.quote
        with engine.begin() as connection:
            tables = set(inspect(connection).get_table_names())
            for table in NEW_TABLES:
                metadata_table = Base.metadata.tables[table]
                if table in tables:
                    applied.append((table, "table", "already_exists"))
                else:
                    metadata_table.create(connection, checkfirst=True)
                    applied.append((table, "table", "created"))

            for table, columns in ADDITIVE_COLUMNS.items():
                if table not in tables:
                    applied.append((table, "table", "skip_missing_legacy_table"))
                    continue
                existing = {
                    column["name"] for column in inspect(connection).get_columns(table)
                }
                for column, definition in columns.items():
                    if column in existing:
                        applied.append((table, column, "already_exists"))
                        continue
                    connection.execute(
                        text(
                            f"ALTER TABLE {quote(table)} ADD COLUMN "
                            f"{quote(column)} {definition}"
                        )
                    )
                    applied.append((table, column, "added"))

                index_names = {
                    index["name"] for index in inspect(connection).get_indexes(table)
                }
                current_columns = {
                    column["name"] for column in inspect(connection).get_columns(table)
                }
                for column in INDEXED_COLUMNS.get(table, ()):
                    index_name = f"ix_{table}_{column}"
                    if column in current_columns and index_name not in index_names:
                        connection.execute(
                            text(
                                f"CREATE INDEX {quote(index_name)} ON "
                                f"{quote(table)} ({quote(column)})"
                            )
                        )
                        applied.append((table, column, "index_added"))
        return applied
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=_database_url())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changes = apply(args.database_url) if args.apply else plan(args.database_url)
    mode = "APPLIED" if args.apply else "PLAN"
    for table, target, action in changes:
        print(f"{mode}\t{table}\t{target}\t{action}")
    if not args.apply:
        print("No database changes made. Back up the database and re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

