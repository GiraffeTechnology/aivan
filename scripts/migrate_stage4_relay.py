"""Add the Stage 4 guided-relay receipt ledger to an existing AIVAN database.

The migration is additive and opt-in. It prints a read-only plan unless
``--apply`` is supplied, and never drops or rewrites existing data.
"""
from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, inspect, text

from aivan.db.models import Base


NEW_TABLES = ("relay_receipts",)
ADDITIVE_COLUMNS = {
    "inquiry_drafts": {
        "channel_account_id": "VARCHAR(128) NOT NULL DEFAULT ''",
    },
}
INDEXED_COLUMNS = {"inquiry_drafts": ("channel_account_id",)}


def _database_url() -> str:
    return os.environ.get("AIVAN_DB_URL", "sqlite:///./data/aiven.db")


def plan(database_url: str) -> list[tuple[str, str, str]]:
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        tables = set(schema.get_table_names())
        changes = [
            (table, "table", "already_exists" if table in tables else "create")
            for table in NEW_TABLES
        ]
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
                if table in tables:
                    applied.append((table, "table", "already_exists"))
                else:
                    Base.metadata.tables[table].create(connection, checkfirst=True)
                    applied.append((table, "table", "created"))
                    tables.add(table)
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
                for column in INDEXED_COLUMNS.get(table, ()):
                    index_name = f"ix_{table}_{column}"
                    if index_name not in index_names:
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
