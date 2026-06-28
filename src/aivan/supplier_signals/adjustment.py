"""Phase 1 deterministic adjustment-factor rules.

Phase 2 (future iteration) will replace these hardcoded factors with AI-derived
values; keep them as a single small table so that swap is localised.
"""

from __future__ import annotations

from aivan.supplier_signals.models import LoadLevel, SupplierStateSignal

# Lead-time multiplier applied to the supplier's non-production stages in GLTG.
_LOAD_FACTOR: dict[LoadLevel, float] = {
    LoadLevel.LIGHT: 1.0,
    LoadLevel.MODERATE: 1.15,
    LoadLevel.HEAVY: 1.40,
    LoadLevel.UNKNOWN: 1.10,
}

# Fallback capacity multiplier when no explicit available_capacity_per_day was
# extracted; conservative (never zero) for UNKNOWN.
_CAPACITY_FACTOR_FALLBACK: dict[LoadLevel, float] = {
    LoadLevel.LIGHT: 1.0,
    LoadLevel.MODERATE: 0.6,
    LoadLevel.HEAVY: 0.25,
    LoadLevel.UNKNOWN: 0.8,
}

# Response-behaviour penalty weights (mirror GLTG SupplierStateOverride): speed
# and completeness each contribute up to 0.15, so the max penalty is 0.30.
_RESPONSE_PENALTY_WEIGHT = 0.15


def load_factor(signal: SupplierStateSignal) -> float:
    """Lead-time multiplier from the signal's load level (defaults to UNKNOWN)."""
    return _LOAD_FACTOR[signal.load_level]


def capacity_factor(signal: SupplierStateSignal) -> float | None:
    """Capacity multiplier for the fallback path.

    Returns None when an explicit available_capacity_per_day is present: that
    value is passed straight to GLTG as a capacity override (no factor needed).
    """
    if signal.available_capacity_per_day is not None:
        return None
    return _CAPACITY_FACTOR_FALLBACK[signal.load_level]


def response_penalty(signal: SupplierStateSignal) -> float:
    """Ranking-score reduction from passive behaviour signals; 0.0 .. 0.30."""
    speed = (1.0 - signal.response_speed_score) * _RESPONSE_PENALTY_WEIGHT
    completeness = (1.0 - signal.completeness_score) * _RESPONSE_PENALTY_WEIGHT
    return round(speed + completeness, 6)
