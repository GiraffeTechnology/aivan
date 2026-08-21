import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from aivan.db.models.migration import SchemaMigrationRecord
from aivan.db.schema_validation import require_current_schema, schema_issues
from scripts.run_aivan_migrations import SCHEMA_VERSION, apply, plan


def test_migration_plan_is_read_only(tmp_path):
    target = tmp_path / "plan.db"
    url = f"sqlite:///{target.as_posix()}"
    result = plan(url, "tenant-1")

    assert result["mode"] == "plan"
    assert not target.exists() or inspect(create_engine(url)).get_table_names() == []


def test_production_startup_schema_validation_is_fail_closed():
    engine = create_engine("sqlite:///:memory:")
    with pytest.raises(RuntimeError, match="migration workflow"):
        require_current_schema(engine)
    assert inspect(engine).get_table_names() == []
    engine.dispose()


def test_empty_database_bootstrap_requires_explicit_flag_and_records_digests(tmp_path):
    target = tmp_path / "apply.db"
    url = f"sqlite:///{target.as_posix()}"
    kwargs = {
        "tenant_id": "tenant-1",
        "candidate_sha": "c" * 40,
        "authorization_reference": "change-123",
        "backup_reference": "backup-456",
    }
    try:
        apply(url, **kwargs)
    except RuntimeError as exc:
        assert "--bootstrap-empty" in str(exc)
    else:
        raise AssertionError("empty production schema must not be bootstrapped implicitly")

    result = apply(url, bootstrap_empty=True, **kwargs)
    assert result["schema_current"] is True
    assert "change-123" not in str(result)
    assert "backup-456" not in str(result)

    engine = create_engine(url)
    assert schema_issues(engine) == []
    with Session(engine) as session:
        record = session.scalar(
            select(SchemaMigrationRecord).where(
                SchemaMigrationRecord.version == SCHEMA_VERSION
            )
        )
        assert record.candidate_sha == "c" * 40
        assert record.authorization_digest != "change-123"
        assert record.backup_digest != "backup-456"
    engine.dispose()
