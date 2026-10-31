"""Scanner inventory uses Git paths without weakening rule or hash coverage."""
import copy
import hashlib
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from tools.security import scan


@pytest.mark.parametrize("separator,relative", [("/", "src/aivan/api/main.py"), ("\\", "src\\aivan\\api\\main.py")])
def test_scanner_report_path_matches_git_inventory(monkeypatch, separator, relative):
    monkeypatch.setattr(scan.os.path, "relpath", lambda *args: relative)
    monkeypatch.setattr(scan.os, "sep", separator)
    assert scan.normalized("unused") == "src/aivan/api/main.py"


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_rule_inventory_uses_portable_relative_paths(monkeypatch, path_type):
    real_tools = scan.TOOLS
    manifest = copy.deepcopy(scan.read_json(real_tools / "semgrep" / "manifest.json"))
    # Isolate path handling from a checkout's line-ending conversion. Production
    # scanning still enforces the unmodified committed manifest and all hashes.
    manifest["license_sha256"] = hashlib.sha256((real_tools / "semgrep" / "LICENSE").read_bytes()).hexdigest()
    for item in manifest["files"]:
        item["sha256"] = hashlib.sha256((real_tools / "semgrep" / item["path"]).read_bytes()).hexdigest()
    monkeypatch.setattr(scan, "read_json", lambda path: manifest)
    class RulePath:
        def __init__(self, path):
            self.path = path
            self.suffix = path.suffix
        def relative_to(self, directory):
            return path_type(self.path.relative_to(real_tools / "semgrep").as_posix())
    class Directory:
        def __truediv__(self, name):
            return real_tools / "semgrep" / name
        def rglob(self, pattern):
            return [RulePath(real_tools / "semgrep" / item["path"]) for item in manifest["files"]]
    class Tools:
        def __truediv__(self, name):
            assert name == "semgrep"
            return Directory()
    monkeypatch.setattr(scan, "TOOLS", Tools())
    assert scan.verify_rules() == manifest
