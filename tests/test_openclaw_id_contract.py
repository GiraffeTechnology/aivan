"""OpenClaw-facing surfaces treat their own ids as a separate namespace.

The repo-wide "no retired giraffe-db id" gate is enforced in CI by the
giraffe-db-owned scanner (see ``.github/workflows/ci.yml``), not by a vendored
AIVAN copy. This module covers only AIVAN's consumer-side behavior: an OpenClaw
sender id is not a giraffe-db DB-backed record id and must never be rejected.
"""

from __future__ import annotations

from aivan.gpm.record_id import validation_error
from aivan.schemas.openclaw import OpenClawEvent


def test_openclaw_sender_id_is_not_a_giraffe_db_record_id():
    """A messaging sender id lives in a separate namespace and is never rejected."""
    event = OpenClawEvent(conversation_id="conv_1", sender_id="supplier_001")
    assert validation_error(event.sender_id) is None
