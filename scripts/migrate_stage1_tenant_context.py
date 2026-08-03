"""Backfill Stage 1 tenant columns for an existing AIVAN database.

The migration is deliberately opt-in. It prints the planned changes unless
``--apply`` is supplied, and it requires the operator to provide the verified
tenant that owns pre-Stage-1 records.
"""
from __future__ import annotations

import argparse
import os
import re

from sqlalchemy import create_engine, inspect, text


TABLES = ("projects", "inquiry_drafts", "processed_inbound_events")
SAFE_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _database_url() -> str:
    return os.environ.get("AIVAN_DB_URL", "sqlite:///./data/aiven.db")


def plan(database_url: str) -> list[tuple[str, str]]:
    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        changes: list[tuple[str, str]] = []
        existing_tables = set(schema.get_table_names())
        for table in TABLES:
            if table not in existing_tables:
                changes.append((table, "skip_missing_table"))
                continue
            columns = {column["name"] for column in schema.get_columns(table)}
            changes.append((table, "already_migrated" if "tenant_id" in columns else "add_tenant_id"))
        return changes
    finally:
        engine.dispose()


def apply(database_url: str, tenant_id: str) -> list[tuple[str, str]]:
    if not SAFE_TENANT.fullmatch(tenant_id):
        raise ValueError("tenant id contains unsupported characters")
    engine = create_engine(database_url)
    applied: list[tuple[str, str]] = []
    try:
        schema = inspect(engine)
        existing_tables = set(schema.get_table_names())
        quote = engine.dialect.identifier_preparer.quote
        with engine.begin() as connection:
            for table in TABLES:
                if table not in existing_tables:
                    applied.append((table, "skip_missing_table"))
                    continue
                columns = {column["name"] for column in inspect(connection).get_columns(table)}
                if "tenant_id" not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {quote(table)} ADD COLUMN tenant_id "
                            f"VARCHAR(128) NOT NULL DEFAULT '{tenant_id}'"
                        )
                    )
                    applied.append((table, "tenant_id_added"))
                else:
                    connection.execute(
                        text(f"UPDATE {quote(table)} SET tenant_id = :tenant WHERE tenant_id IS NULL OR tenant_id = ''"),
                        {"tenant": tenant_id},
                    )
                    applied.append((table, "tenant_id_backfilled"))

                index_name = f"ix_{table}_tenant_id"
                indexes = {index["name"] for index in inspect(connection).get_indexes(table)}
                if index_name not in indexes:
                    connection.execute(
                        text(
                            f"CREATE INDEX {quote(index_name)} ON {quote(table)} (tenant_id)"
                        )
                    )
                    applied.append((table, "tenant_index_added"))
        return applied
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=_database_url())
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changes = apply(args.database_url, args.tenant_id) if args.apply else plan(args.database_url)
    mode = "APPLIED" if args.apply else "PLAN"
    for table, action in changes:
        print(f"{mode}\t{table}\t{action}")
    if not args.apply:
        print("No database changes made. Re-run with --apply after backup and tenant verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
