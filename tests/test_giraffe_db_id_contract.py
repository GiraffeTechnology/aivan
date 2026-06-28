"""giraffe-db record-id contract (consumer side): accept canonical, reject legacy."""

from __future__ import annotations

from aivan.gpm.record_id import (
    is_canonical_giraffe_db_id,
    is_legacy_giraffe_db_id,
    validation_error,
)

# Retired giraffe-db legacy ids used only as invalid input. legacy-id-ok
# Short ids (any digit count) are just as retired as zero-padded ones. legacy-id-ok
LEGACY_INPUTS = [
    "SUP" "_SYN_1", "SUP" "_SYN_01", "SUP" "_SYN_001", "SUP" "_SYN_000001",
    "RFQ" "_SYN_12", "QUOTE" "_SYN_9", "QUOTE" "_SYN_030000", "RISK" "_SYN_000005",
]
CANONICAL_INPUTS = ["GDB_SYN_V1_SUP_000001", "GDB_SYN_V1_QUOTE_030000", "GDB_SYN_V1_RFQ_000012"]
# AIVAN's own (non-giraffe-db) identifiers: a separate namespace, never rejected.
OWN_NAMESPACE = [
    "sup_001", "supplier_001", "supplier_a", "M1", "1688_supplier_001",
    "marketplace_supplier_001", "conversation_supplier_abc", "gpm_pkt_abc123",
]


def test_accepts_canonical():
    for value in CANONICAL_INPUTS:
        assert is_canonical_giraffe_db_id(value)
        assert validation_error(value) is None


def test_rejects_legacy_with_documented_envelope():
    for value in LEGACY_INPUTS:
        assert is_legacy_giraffe_db_id(value)
        err = validation_error(value)
        assert err == {
            "error": "invalid_record_id",
            "expected_format": "GDB_SYN_V1_<ENTITY>_<000001>",
            "received": value,
        }


def test_own_namespace_ids_pass_through():
    for value in OWN_NAMESPACE:
        assert not is_legacy_giraffe_db_id(value)
        assert not is_canonical_giraffe_db_id(value)
        assert validation_error(value) is None


def test_no_silent_remap():
    for value in LEGACY_INPUTS:
        err = validation_error(value)
        assert err["received"] == value
        assert "canonical" not in err
