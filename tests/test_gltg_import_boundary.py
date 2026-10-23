"""Import order must not make the GLTG facade unavailable."""
import subprocess
import sys


def test_gltg_facade_imports_in_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, '-c',
         'from aivan.integrations.gltg import GLTGClient; '
         'assert callable(GLTGClient.simulate)'],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
