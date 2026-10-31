from __future__ import annotations

import os
from sqlalchemy import inspect

from aivan.db.models import Base



def table_is_required(table_name: str) -> bool:
    """Return the existing feature selection without relaxing other tables."""
    if table_name != "ui_test_ticket_receipts":
        return True
    return os.environ.get("AIVAN_UI_TEST_ACCOUNT_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }

def schema_issues(engine) -> list[str]:
    """Return missing table/column identifiers without mutating the database."""

    schema = inspect(engine)
    actual_tables = set(schema.get_table_names())
    issues: list[str] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        # The optional test-login endpoint is closed when disabled. Its own
        # production configuration validation requires this migrated table
        # before enabling or consuming a ticket; normal login does not use it.
        if not table_is_required(table_name):
            continue
        if table_name not in actual_tables:
            issues.append(f"missing_table:{table_name}")
            continue
        actual_columns = {column["name"] for column in schema.get_columns(table_name)}
        for column in table.columns:
            if column.name not in actual_columns:
                issues.append(f"missing_column:{table_name}.{column.name}")
    return issues


def require_current_schema(engine) -> None:
    issues = schema_issues(engine)
    if issues:
        preview = ", ".join(issues[:8])
        suffix = f" (+{len(issues) - 8} more)" if len(issues) > 8 else ""
        raise RuntimeError(
            "Production database schema is not current; run the preview-first "
            f"migration workflow before startup: {preview}{suffix}"
        )
