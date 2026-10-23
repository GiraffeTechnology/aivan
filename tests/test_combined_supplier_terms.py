"""Joint parsing regressions: material substage is not total supplier lead time."""
from __future__ import annotations

import pytest

from aivan.agents import supplier_response_agent as parser


@pytest.mark.parametrize("model_available", [True, False])
def test_material_substage_and_total_lead_time_preserve_separate_source_evidence(
    monkeypatch, model_available,
):
    def completion(*_args):
        if not model_available:
            raise RuntimeError("controlled model unavailable")
        return {"unit_price": 12.5, "currency": "USD", "lead_time_days": 30,
                "confidence": 0.95, "material_declarations": {"forged": True},
                "missing_info": ["payment_terms"]}
    monkeypatch.setattr(parser, "llm_complete_json", completion)
    raw = ("Unit price: 12.50 GBP; production lead time 8.5 days; "
           "raw material lead time: 2.75 days; material availability: partial_stock; "
           "payment due in 30 days.")
    result = parser.parse_supplier_reply(raw, "combined-case", "supplier-1")
    assert result.currency == "GBP"
    assert result.lead_time_days == 8.5
    assert result.material_declarations["fields"]["raw_material_lead_time_estimate_days"] == {
        "value": 2.75, "source_text": "raw material lead time: 2.75 days"}
    assert result.material_declarations["fields"]["material_availability_status"]["value"] == "partial_stock"
    assert "forged" not in result.material_declarations
    assert result.confidence == (0.95 if model_available else 0.4)
    assert result.supplier_id == "supplier-1"


def test_material_only_reply_does_not_fabricate_total_lead_time(monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("controlled model unavailable")
    monkeypatch.setattr(parser, "llm_complete_json", unavailable)
    result = parser.parse_supplier_reply("Raw material lead time: 2.75 days", "combined-case")
    assert result.lead_time_days is None
    assert result.material_declarations["fields"]["raw_material_lead_time_estimate_days"]["value"] == 2.75


def test_total_lead_time_without_material_still_preserves_fraction_and_currency(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_args: {
        "unit_price": 12.5, "currency": "USD", "lead_time_days": 30, "confidence": 0.95,
    })
    result = parser.parse_supplier_reply("Unit price: 12.50 GBP; lead time 8.5 days.", "combined-case")
    assert result.currency == "GBP"
    assert result.lead_time_days == 8.5
