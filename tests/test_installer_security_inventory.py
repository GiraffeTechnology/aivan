"""The installer dependency inventory must not escape the existing OSV gate."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("security_scan_installer", ROOT / "tools/security/scan.py")
SCAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCAN)


def test_installer_inventory_covers_every_pinned_distribution():
    lock = ROOT / "installer/requirements.lock"
    expected = SCAN.expected_packages(str(lock))
    pinned = [line for line in lock.read_text().splitlines() if "==" in line and not line.lstrip().startswith("#")]
    assert len(expected) == len(pinned)
    assert ("PyPI", "ctranslate2", "4.8.2") in expected
    assert ("PyPI", "py3langid", "0.4.0") in expected


@pytest.mark.parametrize("content", [
    "package>=1.0\n", "package==1.0\n", "-r hidden.txt\n", "package @ https://example.invalid/a.whl\n",
    "package==1.0 --hash=sha256:" + "a"*64 + "\npackage==2.0 --hash=sha256:" + "b"*64 + "\n",
])
def test_installer_inventory_rejects_unpinned_or_hidden_dependencies(tmp_path, content):
    path = tmp_path / "requirements.lock"
    path.write_text(content)
    with pytest.raises(RuntimeError):
        SCAN.expected_packages(str(path))
