"""Local reproduction scripts must not reuse attacker-controlled shared paths."""
from pathlib import Path
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("script", ["full_business_closure_e2e.py", "repro_paris_designated_supplier.py"])
def test_reproduction_uses_private_unique_temporary_directory(tmp_path, script):
    root = Path(__file__).resolve().parents[1]
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve")
    for filename in (
        "aivan_full_business_closure_e2e.sqlite3",
        "aivan_full_business_closure_outbox.jsonl",
        "aivan_supplier_replies_e2e.json",
        "aivan_repro_paris.sqlite3",
    ):
        (tmp_path / filename).symlink_to(sentinel)
    code = """
import os
from pathlib import Path
import runpy
import sys

namespaces = [runpy.run_path(sys.argv[1]), runpy.run_path(sys.argv[1])]
directories = [Path(ns['_TEMP_DIRECTORY'].name) for ns in namespaces]
assert directories[0] != directories[1]
for ns, directory in zip(namespaces, directories):
    assert directory.parent == Path(os.environ['TMPDIR'])
    assert directory.stat().st_mode & 0o777 == 0o700
    assert Path(ns['DB_PATH']).parent == directory
    if 'OUTBOX_PATH' in ns:
        assert Path(ns['OUTBOX_PATH']).parent == directory
    ns['_TEMP_DIRECTORY'].cleanup()
    assert not directory.exists()
"""
    environment = os.environ.copy()
    environment.update(TMPDIR=str(tmp_path), PYTHONPATH=os.pathsep.join([str(root / "src"), str(root)]))
    result = subprocess.run(
        [sys.executable, "-c", code, str(root / "scripts" / script)],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_text() == "preserve"
    assert len(list(tmp_path.glob("aivan*"))) == 4
