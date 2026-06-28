"""Combines behaviour observation + LLM extraction into a SupplierStateSignal."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from aivan.supplier_signals.models import (
    ExtractionResult,
    LoadLevel,
    ResponseBehaviour,
    RiskFlag,
    SupplierStateSignal,
)

# A start date further out than this from the enquiry triggers LATE_START.
_LATE_START_DAYS = 30
# Risk-flag thresholds (from the Signal Design table).
_SLOW_RESPONSE_BELOW = 0.3
_INCOMPLETE_BELOW = 0.4


def _risk_flags(
    behaviour: ResponseBehaviour,
    extraction: ExtractionResult,
    enquiry_date: date,
) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    if not behaviour.responded:
        # No reply within 24 working hours: ranked last, carries all flags, never excluded.
        flags.append(RiskFlag.NO_RESPONSE)
    if behaviour.response_speed_score < _SLOW_RESPONSE_BELOW:
        flags.append(RiskFlag.SLOW_RESPONSE)
    if behaviour.completeness_score < _INCOMPLETE_BELOW:
        flags.append(RiskFlag.INCOMPLETE_RESPONSE)
    if extraction.load_level == LoadLevel.HEAVY:
        flags.append(RiskFlag.HIGH_LOAD)
    if (
        extraction.earliest_available_date is not None
        and extraction.earliest_available_date > enquiry_date + timedelta(days=_LATE_START_DAYS)
    ):
        flags.append(RiskFlag.LATE_START)
    return flags


def assemble_signal(
    supplier_id: str,
    enquiry_id: str,
    behaviour: ResponseBehaviour,
    extraction: ExtractionResult,
    enquiry_date: date,
    raw_reply: str | None = None,
    observed_at: datetime | None = None,
) -> SupplierStateSignal:
    """Merge behaviour + extraction into a SupplierStateSignal with risk flags."""
    return SupplierStateSignal(
        supplier_id=supplier_id,
        enquiry_id=enquiry_id,
        observed_at=observed_at or datetime.now(timezone.utc),
        available_capacity_per_day=extraction.available_capacity_per_day,
        earliest_available_date=extraction.earliest_available_date,
        load_level=extraction.load_level,
        response_speed_score=behaviour.response_speed_score,
        completeness_score=behaviour.completeness_score,
        risk_flags=_risk_flags(behaviour, extraction, enquiry_date),
        raw_reply=raw_reply,
        extraction_confidence=extraction.extraction_confidence,
    )
