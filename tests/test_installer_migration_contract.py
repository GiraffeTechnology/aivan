"""Unit-only package/checkout migration boundaries; no target database access."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from aivan.db.models.migration import SchemaMigrationRecord
from scripts import run_aivan_migrations as migrations


def database_controller():
    path = Path(__file__).resolve().parents[1] / "installer/databases.py"
    spec = importlib.util.spec_from_file_location("installer_migration_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_migration_entry_uses_verified_candidate_without_a_checkout(tmp_path, monkeypatch):
    controller = database_controller()
    candidate = "c" * 40
    target = tmp_path / "unit-only.db"
    url = f"sqlite:///{target.as_posix()}"
    manifest = {"components": {"aivan": {"revision": candidate}}}
    snapshot = {"empty": True, "schema_current": False}

    def no_checkout(_):
        raise AssertionError("The verified package path must not require a host Git checkout")

    monkeypatch.setattr(migrations, "_checkout_commit", no_checkout)
    with pytest.raises(ValueError, match="--bootstrap-empty"):
        controller.apply_component(
            "aivan", {"url": url}, snapshot, manifest,
            "tenant-fixture", "synthetic-change", "synthetic-backup", False,
        )
    assert not target.exists()
    result = controller.apply_component(
        "aivan", {"url": url}, snapshot, manifest,
        "tenant-fixture", "synthetic-change", "synthetic-backup", True,
    )
    assert result["candidate_sha"] == candidate
    assert result["schema_version"] == migrations.SCHEMA_VERSION
    assert result["schema_current"] is True
    assert "synthetic-change" not in str(result)
    assert "synthetic-backup" not in str(result)
    engine = create_engine(url)
    try:
        assert "ui_test_ticket_receipts" in inspect(engine).get_table_names()
        with Session(engine) as session:
            receipt = session.scalar(select(SchemaMigrationRecord).where(
                SchemaMigrationRecord.version == migrations.SCHEMA_VERSION
            ))
            assert receipt.candidate_sha == candidate
            assert receipt.authorization_digest == hashlib.sha256(b"synthetic-change").hexdigest()
            assert receipt.backup_digest == hashlib.sha256(b"synthetic-backup").hexdigest()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("candidate", "tenant", "authorization", "backup", "error"),
    [
        ("not-a-full-sha", "tenant-fixture", "change", "backup", "candidate SHA"),
        ("c" * 40, "", "change", "backup", "tenant id"),
        ("c" * 40, "tenant-fixture", "", "backup", "authorization"),
        ("c" * 40, "tenant-fixture", "change", "", "backup"),
    ],
)
def test_packaged_migration_preserves_candidate_and_authorization_guards(
    tmp_path, candidate, tenant, authorization, backup, error,
):
    controller = database_controller()
    target = tmp_path / "must-not-exist.db"
    with pytest.raises(ValueError, match=error):
        controller.apply_component(
            "aivan", {"url": f"sqlite:///{target.as_posix()}"},
            {"empty": False, "schema_current": False},
            {"components": {"aivan": {"revision": candidate}}},
            tenant, authorization, backup, False,
        )
    assert not target.exists()


def test_aivan_preview_reports_the_selected_runner_schema_version(tmp_path, monkeypatch):
    controller = database_controller()
    target = tmp_path / "preview-unit-only.db"
    monkeypatch.setattr(
        controller.CONFIG, "physical_namespace",
        lambda engine, selected: ("unit-fixture", "isolated"),
    )
    snapshot = controller.inspect_target(
        "aivan",
        {"url": f"sqlite:///{target.as_posix()}", "schema": "main",
         "engine": "unit-fixture", "target_sha256": "d" * 64},
    )
    assert snapshot["target_revisions"] == [migrations.SCHEMA_VERSION]
    assert snapshot["schema_current"] is False
    assert snapshot["empty"] is True
    engine = create_engine(f"sqlite:///{target.as_posix()}")
    try:
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_tampered_package_is_rejected_before_database_configuration(tmp_path, monkeypatch):
    controller = database_controller()
    payload = tmp_path / "payload"
    payload.mkdir()
    asset = payload / "migration.py"
    asset.write_text("tampered unit fixture")
    (payload / "manifest.json").write_text(json.dumps({
        "files": {"migration.py": "0" * 64},
    }))
    monkeypatch.setattr(controller, "HERE", payload)

    def no_target_access(*args, **kwargs):
        raise AssertionError("A tampered package must not inspect database targets")

    monkeypatch.setattr(controller.CONFIG, "configured_targets", no_target_access)
    with pytest.raises(ValueError, match="Package integrity mismatch"):
        controller.plan(tmp_path / "installation")
