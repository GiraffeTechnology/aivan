"""Source-declared lead time is not offer validity, payment term or model rounding."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.mark.parametrize("text,model_days,expected", [
    ("Unit price: 12.50 GBP; lead time 8.5 days; payment due in 30 days.", 30, 8.5),
    ("Unit price: 12.50 GBP; offer valid for 2 days; production lead time 8.5 days.", 2, 8.5),
    ("Unit price: 12.50 GBP; lead time 0.5 days.", 1, 0.5),
    ("Unit price: 12.50 GBP; lead time 0 days.", 1, 0),
])
def test_model_cannot_replace_literal_supplier_lead_time(monkeypatch, text, model_days, expected):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": model_days,
        "confidence": 0.95, "missing_info": [],
    })
    result = parser.parse_supplier_reply(text, "lead-case", "supplier-1")
    assert result.lead_time_days == expected
    assert result.confidence == 0.95
    assert result.unit_price == 12.5
    assert result.supplier_id == "supplier-1"


def test_model_cannot_resolve_explicit_lead_time_alternatives(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": 8.5, "confidence": 0.95,
    })
    result = parser.parse_supplier_reply(
        "Unit price: 12.50 GBP; lead time 8.5 days or 10 days.", "lead-case")
    assert result.lead_time_days is None
    assert "lead_time_days" in result.missing_info
    assert result.confidence == 0.95


def test_explicit_lead_time_supplies_model_omission_without_losing_other_missing_fields(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "confidence": 0.95,
        "missing_info": ["lead_time_days", "payment_terms"],
    })
    result = parser.parse_supplier_reply("Unit price: 12.50 GBP; lead time 8.5 days.", "lead-case")
    assert result.lead_time_days == 8.5
    assert result.missing_info == ["payment_terms"]


def test_semantic_duration_outside_literal_day_parser_remains_supported(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": 10.5, "confidence": 0.95,
    })
    result = parser.parse_supplier_reply(
        "Unit price: 12.50 GBP; production takes one and a half weeks.", "lead-case")
    assert result.lead_time_days == 10.5
    assert result.confidence == 0.95


def test_consistent_model_and_literal_evidence_preserve_caller_identity(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "GBP", "lead_time_days": 8.5, "confidence": 0.95,
        "project_id": "untrusted-case", "supplier_id": "untrusted-supplier",
        "candidate_id": "untrusted-candidate", "source_event_id": "untrusted-event",
    })
    result = parser.parse_supplier_reply(
        "Unit price: 12.50 GBP; lead time 8.5 days.", "lead-case", "supplier-1", "candidate-1")
    assert result.lead_time_days == 8.5
    assert (result.project_id, result.supplier_id, result.candidate_id) == (
        "lead-case", "supplier-1", "candidate-1")
    assert result.source_event_id == ""
