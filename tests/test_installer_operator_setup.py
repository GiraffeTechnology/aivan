"""Operator input remains local, private, encoded and free of implicit grants."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("operator_setup_tests", ROOT / "installer/operator_setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_mysql_values_are_encoded_without_exposing_existing_password(capsys):
    values = iter(["127.0.0.1", "3307", "test_database", "test@user"])
    result = setup.mysql_descriptor("aivan", "pymysql", input_value=lambda _prompt: next(values), secret_value=lambda _prompt: "synthetic:p@ss/word")
    assert result["url"] == "mysql+pymysql://test%40user:synthetic%3Ap%40ss%2Fword@127.0.0.1:3307/test_database"
    assert "synthetic:p" not in capsys.readouterr().out


def test_private_writer_is_owner_only_and_refuses_accidental_replacement(tmp_path):
    path = tmp_path / "operator.json"
    setup.write_private(path, {"version": 1})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="already exists"):
        setup.write_private(path, {"replacement": True})
    assert json.loads(path.read_text()) == {"version": 1}
    setup.write_private(path, {"version": 2}, replace=True)
    assert json.loads(path.read_text()) == {"version": 2}


def test_private_writer_rejects_symlink_and_public_existing_file(tmp_path):
    path = tmp_path / "operator.json"
    path.write_text("retain")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        setup.write_private(path, {}, replace=True)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        setup.write_private(link, {}, replace=True)
    assert path.read_text() == "retain"


def test_noninteractive_password_entry_never_falls_back_to_echo(monkeypatch):
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="interactive terminal"):
        setup.require_terminal()
