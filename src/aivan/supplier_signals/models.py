"""Data models for the supplier real-time state-signal layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class LoadLevel(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"
    UNKNOWN = "UNKNOWN"


class RiskFlag(str, Enum):
    SLOW_RESPONSE = "SLOW_RESPONSE"
    INCOMPLETE_RESPONSE = "INCOMPLETE_RESPONSE"
    HIGH_LOAD = "HIGH_LOAD"
    LATE_START = "LATE_START"
    NO_RESPONSE = "NO_RESPONSE"


@dataclass
class EnquiryContext:
    """Order context handed to the extractor so it can reason about capacity."""

    quantity: int
    product_type: str
    enquiry_date: date


@dataclass
class ResponseBehaviour:
    """Pure deterministic behaviour observation (no LLM)."""

    response_speed_score: float = 1.0   # 0.0-1.0
    completeness_score: float = 1.0     # 0.0-1.0
    responded: bool = True              # False -> no reply within 24 working hours
    actual_working_hours: float | None = None
    found_topics: int = 0               # of the 3 questionnaire topics


@dataclass
class ExtractionResult:
    """Structured fields extracted from a free-text supplier reply by the LLM."""

    available_capacity_per_day: int | None = None
    earliest_available_date: date | None = None
    load_level: LoadLevel = LoadLevel.UNKNOWN
    extraction_confidence: float = 1.0  # 0.0-1.0
    extraction_notes: str = ""
    provider: str = ""                  # which LLM produced the result

    @classmethod
    def empty(cls, notes: str = "", provider: str = "") -> "ExtractionResult":
        """All-null result; never fabricates fields."""
        return cls(
            available_capacity_per_day=None,
            earliest_available_date=None,
            load_level=LoadLevel.UNKNOWN,
            extraction_confidence=0.0,
            extraction_notes=notes,
            provider=provider,
        )


@dataclass
class SupplierStateSignal:
    supplier_id: str
    enquiry_id: str
    observed_at: datetime

    # Active signals (LLM-extracted).
    available_capacity_per_day: int | None = None
    earliest_available_date: date | None = None
    load_level: LoadLevel = LoadLevel.UNKNOWN

    # Passive signals (behaviour-observed).
    response_speed_score: float = 1.0
    completeness_score: float = 1.0

    # Derived.
    risk_flags: list[RiskFlag] = field(default_factory=list)
    raw_reply: str | None = None
    extraction_confidence: float = 1.0
