from __future__ import annotations

import pytest

from aivan.db.session import _get_db_url


def test_default_database_uses_canonical_aivan_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIVAN_DB_URL", raising=False)

    assert _get_db_url() == "sqlite:///./data/aivan.db"


def test_production_requires_explicit_database_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIVAN_DB_URL", raising=False)
    monkeypatch.setenv("AIVAN_ENV", "production")

    with pytest.raises(RuntimeError, match="AIVAN_DB_URL is required in production"):
        _get_db_url()


def test_legacy_database_is_reused_instead_of_silently_splitting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIVAN_DB_URL", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (data / "aiven.db").touch()

    assert _get_db_url() == "sqlite:///./data/aiven.db"


def test_ambiguous_default_databases_require_explicit_selection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIVAN_DB_URL", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    (data / "aiven.db").touch()
    (data / "aivan.db").touch()

    with pytest.raises(RuntimeError, match="set AIVAN_DB_URL explicitly"):
        _get_db_url()
