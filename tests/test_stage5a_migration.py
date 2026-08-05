import json

from sqlalchemy import create_engine, inspect, text

from scripts.migrate_stage5a_event_correction import apply, plan


def _legacy_database(tmp_path) -> str:
    database_url = f"sqlite:///{tmp_path / 'stage5a-legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE execution_events ("
                "event_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128), "
                "project_id VARCHAR(64), event_type VARCHAR(128), summary TEXT, "
                "payload_json JSON, before_json JSON, after_json JSON)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO execution_events VALUES "
                "('event-1', 'tenant-a', 'case-1', 'STRATEGY_UPDATED', 'updated', "
                ":payload, :before, :after)"
            ),
            {
                "payload": json.dumps({"priority": "speed"}),
                "before": json.dumps({"strategy": {"priority": "cost"}}),
                "after": json.dumps({"strategy": {"priority": "speed"}}),
            },
        )
    engine.dispose()
    return database_url


def test_stage5a_migration_is_additive_idempotent_and_backfills_digest(tmp_path):
    database_url = _legacy_database(tmp_path)
    assert ("event_reversals", "table", "create") in plan(database_url)
    assert ("execution_events", "payload_digest", "add") in plan(database_url)
    first = apply(database_url)
    second = apply(database_url)
    assert ("event_reversals", "table", "created") in first
    assert ("event_reversals", "table", "already_exists") in second

    engine = create_engine(database_url)
    schema = inspect(engine)
    assert "event_reversals" in schema.get_table_names()
    columns = {column["name"] for column in schema.get_columns("execution_events")}
    assert {"derived_from_event_id", "payload_digest", "correction_status"} <= columns
    with engine.connect() as connection:
        digest = connection.execute(
            text("SELECT payload_digest FROM execution_events WHERE event_id='event-1'")
        ).scalar_one()
    assert len(digest) == 64
    engine.dispose()
