from sqlalchemy import create_engine, inspect, text

from scripts.migrate_stage4_relay import apply, plan


def _legacy_database(tmp_path) -> str:
    database_url = f"sqlite:///{tmp_path / 'stage4-legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE inquiry_drafts (draft_id VARCHAR(64) PRIMARY KEY, "
                "tenant_id VARCHAR(128), project_id VARCHAR(64))"
            )
        )
    engine.dispose()
    return database_url


def test_stage4_migration_is_previewable_additive_and_idempotent(tmp_path):
    database_url = _legacy_database(tmp_path)
    assert ("relay_receipts", "table", "create") in plan(database_url)
    assert ("inquiry_drafts", "channel_account_id", "add") in plan(database_url)

    first = apply(database_url)
    second = apply(database_url)
    assert ("relay_receipts", "table", "created") in first
    assert ("relay_receipts", "table", "already_exists") in second

    engine = create_engine(database_url)
    schema = inspect(engine)
    assert "relay_receipts" in schema.get_table_names()
    assert "channel_account_id" in {
        column["name"] for column in schema.get_columns("inquiry_drafts")
    }
    engine.dispose()
