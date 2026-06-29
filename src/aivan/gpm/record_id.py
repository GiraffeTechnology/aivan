"""giraffe-db record-id contract (consumer side).

Ownership:

* giraffe-db owns the canonical DB record-ID contract. The authoritative
  definition (entity codes, canonical/legacy regexes, generator, scanner,
  reusable tests) lives in ``GiraffeTechnology/giraffe-db``
  (``generators/id_convention.py`` + ``scripts/check_unified_data_ids.py``).
* AIVAN does **not** define the canonical DB contract and does not vendor the
  cross-repo scanner. CI consumes the giraffe-db-owned scanner instead.
* This module performs only *consumer-side request-boundary validation*: when a
  value entering an AIVAN route is meant to be a giraffe-db DB-backed record id,
  a retired ``<ENTITY>_SYN_<digits>`` legacy id is rejected -- never silently
  remapped. The entity codes / patterns below are a minimal local mirror of the
  giraffe-db contract, kept narrow on purpose; they are not a second source of
  truth.
* AIVAN's own identifier namespace is separate and stays valid. ``sup_001``,
  ``supplier_001``, marketplace ids, conversation-derived ids, OpenClaw sender
  ids, ``gpm_pkt_*`` and ``tenant_id`` are passed through untouched. Only the
  unambiguous retired giraffe-db legacy shape is treated as invalid input.
"""

from __future__ import annotations

import re

# Entity codes published by giraffe-db (generators/id_convention.py).
ENTITY_CODES = (
    "SUP", "PROD", "CAP", "CUST", "PREF", "RFQ", "QUOTE", "OBS", "RISK",
    "LINEAGE", "IMPORT",
)

CANONICAL_RE = re.compile(r"^GDB_SYN_V1_(?:" + "|".join(ENTITY_CODES) + r")_[0-9]{6}$")
# Retired legacy ids are rejected regardless of digit count: an unpadded
# single-digit suffix is just as retired as a zero-padded six-digit one.
LEGACY_DB_ID_RE = re.compile(r"^(?:" + "|".join(ENTITY_CODES) + r")_SYN_[0-9]+$")

EXPECTED_ID_FORMAT = "GDB_SYN_V1_<ENTITY>_<000001>"


def is_canonical_giraffe_db_id(value: str) -> bool:
    return bool(CANONICAL_RE.match(value or ""))


def is_legacy_giraffe_db_id(value: str) -> bool:
    """True only for the unambiguous retired giraffe-db record-id shape."""
    return bool(LEGACY_DB_ID_RE.match(value or ""))


def validation_error(value: str) -> dict[str, str] | None:
    """Return the documented error envelope for a retired legacy id, else None.

    AIVAN's own non-giraffe-db identifiers return None (accepted as-is).
    """
    if is_legacy_giraffe_db_id(value):
        return {
            "error": "invalid_record_id",
            "expected_format": EXPECTED_ID_FORMAT,
            "received": value,
        }
    return None
