"""Tests for the signal assembler / risk-flag logic (Task 1)."""

from __future__ import annotations

from datetime import date

from aivan.supplier_signals.assembler import assemble_signal
from aivan.supplier_signals.behaviour_observer import no_response_behaviour
from aivan.supplier_signals.models import (
    ExtractionResult,
    LoadLevel,
    ResponseBehaviour,
    RiskFlag,
)

ENQUIRY_DATE = date(2026, 6, 27)


def _assemble(behaviour, extraction):
    return assemble_signal("S1", "ENQ1", behaviour, extraction, ENQUIRY_DATE)


def test_slow_response_flag():
    sig = _assemble(ResponseBehaviour(response_speed_score=0.2, completeness_score=1.0), ExtractionResult())
    assert RiskFlag.SLOW_RESPONSE in sig.risk_flags


def test_incomplete_response_flag():
    sig = _assemble(ResponseBehaviour(response_speed_score=1.0, completeness_score=0.33), ExtractionResult())
    assert RiskFlag.INCOMPLETE_RESPONSE in sig.risk_flags


def test_high_load_flag():
    sig = _assemble(ResponseBehaviour(), ExtractionResult(load_level=LoadLevel.HEAVY, extraction_confidence=0.9))
    assert RiskFlag.HIGH_LOAD in sig.risk_flags
    assert sig.load_level == LoadLevel.HEAVY


def test_late_start_flag():
    late = date(2026, 6, 27).replace(day=27)
    extraction = ExtractionResult(earliest_available_date=date(2026, 8, 1), extraction_confidence=0.9)
    sig = _assemble(ResponseBehaviour(), extraction)  # 2026-08-01 > enquiry + 30d (2026-07-27)
    assert RiskFlag.LATE_START in sig.risk_flags


def test_late_start_not_flagged_within_window():
    extraction = ExtractionResult(earliest_available_date=date(2026, 7, 20), extraction_confidence=0.9)
    sig = _assemble(ResponseBehaviour(), extraction)  # within 30 days
    assert RiskFlag.LATE_START not in sig.risk_flags


def test_no_response_flag_and_zero_scores():
    sig = _assemble(no_response_behaviour(), ExtractionResult.empty())
    assert RiskFlag.NO_RESPONSE in sig.risk_flags
    # No reply -> slow + incomplete also true (scores are 0.0); all carried, never excluded.
    assert RiskFlag.SLOW_RESPONSE in sig.risk_flags
    assert RiskFlag.INCOMPLETE_RESPONSE in sig.risk_flags
    assert sig.response_speed_score == 0.0
    assert sig.completeness_score == 0.0


def test_clean_signal_has_no_flags():
    behaviour = ResponseBehaviour(response_speed_score=1.0, completeness_score=1.0)
    extraction = ExtractionResult(
        available_capacity_per_day=2000, load_level=LoadLevel.LIGHT, extraction_confidence=0.9
    )
    sig = _assemble(behaviour, extraction)
    assert sig.risk_flags == []
    assert sig.available_capacity_per_day == 2000
