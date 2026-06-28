"""OpenClaw-facing surfaces carry no retired giraffe-db record ids."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from aivan.gpm.record_id import validation_error
from aivan.schemas.openclaw import OpenClawEvent

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_legacy_giraffe_db_ids_in_repo():
    """Scanner error tier (retired DB-record ids) must be empty across the repo."""
    result = subprocess.run(
        [sys.executable, "scripts/check_unified_data_ids.py", "--repo", "."],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: PASS" in result.stdout


def test_openclaw_sender_id_is_not_a_giraffe_db_record_id():
    """A messaging sender id lives in a separate namespace and is never rejected."""
    event = OpenClawEvent(conversation_id="conv_1", sender_id="supplier_001")
    assert validation_error(event.sender_id) is None
