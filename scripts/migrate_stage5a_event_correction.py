"""Add Stage 5A event lineage, digests, and the reversal ledger.

The migration is additive and preview-first. Existing events receive a stable
payload digest; no source event or business record is deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os

from sqlalchemy import create_engine, inspect, text

from aivan.db.models import Base


NEW_TABLES = ("event_reversals",)
ADDITIVE_COLUMNS = {
    "execution_events": {
        "derived_from_event_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "payload_digest": "VARCHAR(64) NOT NULL DEFAULT ''",
        "correction_status": "VARCHAR(32) NOT NULL DEFAULT ''",
    }
}
INDEXED_COLUMNS = {
    "execution_events": (
        "derived_from_event_id",
        "payload_digest",
        "correction_status",
    )
}


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


def _digest_row(row: dict) -> str:
    payload = {
        "event_type": row.get("event_type") or "",
        "summary": row.get("summary") or "",
        "payload": row.get("payload_json") or {},
        "before": row.get("before_json") or {},
        "after": row.get("after_json") or {},
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backfill_digests(connection, table: str) -> int:
    schema = inspect(connection)
    columns = {column["name"] for column in schema.get_columns(table)}
    if not {"event_id", "payload_digest"} <= columns:
        return 0
    readable = [
        name
        for name in (
            "event_id",
            "event_type",
            "summary",
            "payload_json",
            "before_json",
            "after_json",
            "payload_digest",
        )
        if name in columns
    ]
    quote = connection.dialect.identifier_preparer.quote
    rows = connection.execute(
        text(
            f"SELECT {', '.join(quote(name) for name in readable)} "
            f"FROM {quote(table)}"
        )
    ).mappings()
    count = 0
    for row in rows:
        data = dict(row)
        if data.get("payload_digest"):
            continue
        connection.execute(
            text(
                f"UPDATE {quote(table)} SET {quote('payload_digest')} = :digest "
                f"WHERE {quote('event_id')} = :event_id"
            ),
            {"digest": _digest_row(data), "event_id": data["event_id"]},
        )
        count += 1
    return count


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
                    tables.add(table)
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
                    else:
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
                backfilled = _backfill_digests(connection, table)
                applied.append((table, "payload_digest", f"backfilled_{backfilled}"))
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
