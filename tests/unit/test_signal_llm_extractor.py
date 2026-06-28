"""Tests for the LLM extraction layer (Task 1)."""

from __future__ import annotations

from datetime import date

import pytest

from aivan.supplier_signals.llm_extractor import extract_supplier_state
from aivan.supplier_signals.models import EnquiryContext, LoadLevel

CONTEXT = EnquiryContext(quantity=10000, product_type="men_shirt", enquiry_date=date(2026, 6, 27))


class FakeProvider:
    def __init__(self, name, result=None, exc=None):
        self.provider_name = name
        self._result = result or {}
        self._exc = exc
        self.calls = 0

    def complete_json(self, task, system_prompt, user_prompt, schema_hint, temperature=0.0):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


class _Resp:
    def __init__(self, status):
        self.status_code = status


class HTTPStatusError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = _Resp(status)


def test_valid_json_extracts_fields():
    primary = FakeProvider("ollama", result={
        "available_capacity_per_day": 1500,
        "earliest_available_date": "2026-07-15",
        "load_level": "HEAVY",
        "extraction_confidence": 0.9,
        "extraction_notes": "clear",
    })
    fallback = FakeProvider("qwen")
    result = extract_supplier_state("现在比较忙", CONTEXT, primary=primary, fallback=fallback)
    assert result.available_capacity_per_day == 1500
    assert result.earliest_available_date == date(2026, 7, 15)
    assert result.load_level == LoadLevel.HEAVY
    assert result.provider == "ollama"
    assert fallback.calls == 0


def test_timeout_falls_back_to_dashscope():
    primary = FakeProvider("ollama", exc=TimeoutError("local model timed out"))
    fallback = FakeProvider("qwen", result={
        "available_capacity_per_day": 800,
        "load_level": "MODERATE",
        "extraction_confidence": 0.7,
    })
    result = extract_supplier_state("text", CONTEXT, primary=primary, fallback=fallback)
    assert fallback.calls == 1
    assert result.provider == "qwen"
    assert result.available_capacity_per_day == 800
    assert result.load_level == LoadLevel.MODERATE


def test_4xx_does_not_fall_back():
    primary = FakeProvider("ollama", exc=HTTPStatusError(400))
    fallback = FakeProvider("qwen", result={"extraction_confidence": 0.9, "load_level": "LIGHT"})
    result = extract_supplier_state("text", CONTEXT, primary=primary, fallback=fallback)
    assert fallback.calls == 0  # bad request: fix the prompt, not the client
    assert result.available_capacity_per_day is None
    assert result.load_level == LoadLevel.UNKNOWN


def test_low_confidence_nulls_all_fields():
    primary = FakeProvider("ollama", result={
        "available_capacity_per_day": 1500,
        "earliest_available_date": "2026-07-15",
        "load_level": "HEAVY",
        "extraction_confidence": 0.3,
        "extraction_notes": "ambiguous, off-topic reply",
    })
    result = extract_supplier_state("不太清楚", CONTEXT, primary=primary, fallback=FakeProvider("qwen"))
    assert result.available_capacity_per_day is None
    assert result.earliest_available_date is None
    assert result.load_level == LoadLevel.UNKNOWN
    assert result.extraction_confidence == 0.3


def test_capacity_range_takes_conservative_lower_bound():
    primary = FakeProvider("ollama", result={
        "available_capacity_per_day": "1000-1500件",
        "load_level": "MODERATE",
        "extraction_confidence": 0.8,
    })
    result = extract_supplier_state("日产1000到1500件", CONTEXT, primary=primary, fallback=FakeProvider("qwen"))
    assert result.available_capacity_per_day == 1000


def test_both_providers_fail_returns_empty_never_raises():
    primary = FakeProvider("ollama", exc=ConnectionError("down"))
    fallback = FakeProvider("qwen", exc=RuntimeError("also down"))
    result = extract_supplier_state("text", CONTEXT, primary=primary, fallback=fallback)
    assert result.available_capacity_per_day is None
    assert result.load_level == LoadLevel.UNKNOWN
    assert result.extraction_confidence == 0.0
