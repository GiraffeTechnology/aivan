from sqlalchemy import create_engine, inspect, text

from scripts.migrate_stage2_role_domain import NEW_TABLES, apply, plan


def _legacy_database(tmp_path) -> str:
    database_url = f"sqlite:///{tmp_path / 'stage2-legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE projects (project_id VARCHAR(64) PRIMARY KEY, "
                "conversation_id VARCHAR(128), customer_id VARCHAR(128))"
            )
        )
        connection.execute(text("CREATE TABLE openclaw_accounts (account_connection_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE user_preferences (preference_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE suppliers (supplier_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE platforms (platform_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO openclaw_accounts VALUES ('legacy-account')"))
        connection.execute(text("INSERT INTO suppliers VALUES ('legacy-supplier')"))
        connection.execute(text("INSERT INTO platforms VALUES ('legacy-platform')"))
        connection.execute(
            text(
                "CREATE TABLE inquiry_drafts (draft_id VARCHAR(64) PRIMARY KEY, "
                "project_id VARCHAR(64))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE execution_events (event_id VARCHAR(64) PRIMARY KEY, "
                "project_id VARCHAR(64))"
            )
        )
    engine.dispose()
    return database_url


def test_stage2_migration_preview_is_read_only(tmp_path):
    database_url = _legacy_database(tmp_path)
    preview = plan(database_url)
    assert ("case_conversations", "table", "create") in preview
    assert ("projects", "case_state", "add") in preview

    engine = create_engine(database_url)
    assert "case_conversations" not in inspect(engine).get_table_names()
    engine.dispose()


def test_stage2_migration_is_additive_and_idempotent(tmp_path):
    database_url = _legacy_database(tmp_path)
    first = apply(database_url)
    second = apply(database_url)

    assert ("case_conversations", "table", "created") in first
    assert ("case_conversations", "table", "already_exists") in second
    engine = create_engine(database_url)
    schema = inspect(engine)
    tables = set(schema.get_table_names())
    assert set(NEW_TABLES) <= tables
    project_columns = {column["name"] for column in schema.get_columns("projects")}
    assert {"case_state", "source_trace_id"} <= project_columns
    draft_columns = {
        column["name"] for column in schema.get_columns("inquiry_drafts")
    }
    assert {"participant_id", "source_trace_id", "approval_id"} <= draft_columns
    event_columns = {
        column["name"] for column in schema.get_columns("execution_events")
    }
    assert {
        "tenant_id",
        "source_trace_id",
        "actor_id",
        "actor_role",
        "before_json",
        "after_json",
        "rejection_reason",
    } <= event_columns
    for table in ("openclaw_accounts", "user_preferences", "suppliers", "platforms"):
        assert "tenant_id" in {column["name"] for column in schema.get_columns(table)}
    assert "logical_account_connection_id" in {column["name"] for column in schema.get_columns("openclaw_accounts")}
    assert "logical_supplier_id" in {column["name"] for column in schema.get_columns("suppliers")}
    assert "logical_platform_id" in {column["name"] for column in schema.get_columns("platforms")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT logical_account_connection_id FROM openclaw_accounts")).scalar_one() == "legacy-account"
        assert connection.execute(text("SELECT logical_supplier_id FROM suppliers")).scalar_one() == "legacy-supplier"
        assert connection.execute(text("SELECT logical_platform_id FROM platforms")).scalar_one() == "legacy-platform"
    message_columns = {column["name"] for column in schema.get_columns("case_messages")}
    assert {"asserted_by_actor_id", "asserted_by_actor_role"} <= message_columns
    engine.dispose()

