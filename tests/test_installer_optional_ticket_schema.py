"""Keep optional Aivan authentication schema consistent across installer callers."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

from aivan.db.models import Base
from aivan.db.schema_validation import schema_issues as core_schema_issues


def installer_schema():
    path = Path(__file__).resolve().parents[1] / "installer/database_config.py"
    spec = importlib.util.spec_from_file_location("optional_ticket_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def schema_without_ticket():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[table for table in Base.metadata.tables.values()
                        if table.name != "ui_test_ticket_receipts"],
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("enabled", ["", "false", "0", "true", "yes", "1"])
def test_installer_matches_core_optional_ticket_requirement(
    schema_without_ticket, monkeypatch, enabled,
):
    monkeypatch.setenv("AIVAN_UI_TEST_ACCOUNT_ENABLED", enabled)
    helper = installer_schema()
    actual = helper.schema_issues(schema_without_ticket, Base.metadata)
    assert actual == sorted(core_schema_issues(schema_without_ticket))
    if enabled in {"true", "yes", "1"}:
        assert actual == ["missing_table:ui_test_ticket_receipts"]
        with pytest.raises(RuntimeError, match="compatible"):
            helper.require_schema(schema_without_ticket, Base.metadata)
    else:
        assert actual == []
        helper.require_schema(schema_without_ticket, Base.metadata)
    assert "ui_test_ticket_receipts" not in inspect(schema_without_ticket).get_table_names()


def test_disabled_ticket_does_not_hide_other_missing_aivan_tables(monkeypatch):
    monkeypatch.setenv("AIVAN_UI_TEST_ACCOUNT_ENABLED", "false")
    engine = create_engine("sqlite:///:memory:")
    required = next(table for table in Base.metadata.tables.values()
                    if table.name != "ui_test_ticket_receipts")
    Base.metadata.create_all(
        engine, tables=[table for table in Base.metadata.tables.values()
                        if table.name not in {"ui_test_ticket_receipts", required.name}],
    )
    try:
        issues = installer_schema().schema_issues(engine, Base.metadata)
        assert issues == [f"missing_table:{required.name}"]
    finally:
        engine.dispose()


def test_a_different_metadata_owner_cannot_inherit_the_optional_exception(monkeypatch):
    monkeypatch.setenv("AIVAN_UI_TEST_ACCOUNT_ENABLED", "false")
    metadata = MetaData()
    Table("ui_test_ticket_receipts", metadata, Column("digest", String(64), primary_key=True))
    engine = create_engine("sqlite:///:memory:")
    try:
        assert installer_schema().schema_issues(engine, metadata) == [
            "missing_table:ui_test_ticket_receipts"
        ]
    finally:
        engine.dispose()


@pytest.mark.parametrize("enabled", ["false", "true"])
def test_present_incomplete_ticket_schema_matches_core_selection(
    schema_without_ticket, monkeypatch, enabled,
):
    monkeypatch.setenv("AIVAN_UI_TEST_ACCOUNT_ENABLED", enabled)
    partial = MetaData()
    Table("ui_test_ticket_receipts", partial, Column("digest", String(64), primary_key=True))
    partial.create_all(schema_without_ticket)
    actual = installer_schema().schema_issues(schema_without_ticket, Base.metadata)
    assert actual == sorted(core_schema_issues(schema_without_ticket))
    if enabled == "true":
        assert "missing_column:ui_test_ticket_receipts.expires_at" in actual
        assert "missing_column:ui_test_ticket_receipts.consumed_at" in actual
    else:
        assert actual == []
