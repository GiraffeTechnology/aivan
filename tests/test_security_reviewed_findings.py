"""A narrow reviewed finding cannot exempt new content or unrelated findings."""
import hashlib

import pytest

from tools.security import scan


def reviewed_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source.js"
    source.write_text("fixed fixture\n")
    exception = {
        "rule": "fixture-rule", "path": "source.js", "count": 1,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reason": "Controlled regression fixture only",
    }
    monkeypatch.setattr(scan, "read_json", lambda path: {"semgrep": [exception]})
    finding = {"check_id": "fixture-rule", "path": "source.js"}
    return source, exception, finding


def test_reviewed_exact_finding_keeps_unrelated_rule_blocking(tmp_path, monkeypatch):
    _, exception, finding = reviewed_fixture(tmp_path, monkeypatch)
    unrelated = {"check_id": "other-rule", "path": "source.js"}
    pending, waived = scan.reviewed_findings("semgrep", [finding, unrelated])
    assert pending == [unrelated]
    assert waived == [exception]


def test_reviewed_changed_content_fails_closed(tmp_path, monkeypatch):
    source, _, finding = reviewed_fixture(tmp_path, monkeypatch)
    source.write_text("changed fixture\n")
    with pytest.raises(RuntimeError, match="fingerprint changed"):
        scan.reviewed_findings("semgrep", [finding])


def test_reviewed_additional_occurrence_fails_closed(tmp_path, monkeypatch):
    _, _, finding = reviewed_fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="count changed"):
        scan.reviewed_findings("semgrep", [finding, dict(finding)])


def test_reviewed_other_path_cannot_inherit_exception(tmp_path, monkeypatch):
    _, _, finding = reviewed_fixture(tmp_path, monkeypatch)
    finding["path"] = "other.js"
    pending, waived = scan.reviewed_findings("semgrep", [finding])
    assert pending == [finding]
    assert waived == []
