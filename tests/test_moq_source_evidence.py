"""Explicit supplier minimums cannot be replaced by model guesses or prefixes."""
import pytest

from aivan.agents import supplier_response_agent as parser
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement


@pytest.mark.parametrize("model_moq", [10000, None, 100])
@pytest.mark.parametrize("literal,expected", [("100", 100), ("1,000", 1000), ("0", 0)])
def test_literal_moq_overrides_incorrect_or_missing_model_value(monkeypatch, model_moq, literal, expected):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 4.5, "currency": "USD", "moq": model_moq,
        "missing_info": ["moq"], "confidence": 0.95})
    reply = parser.parse_supplier_reply(f"Unit price USD 4.50; MOQ {literal} pcs; lead time 35 days.",
                                       project_id="case-unit", supplier_id="supplier-unit")
    assert reply.moq == expected
    assert "moq" not in reply.missing_info


@pytest.mark.parametrize("model_available", [True, False])
@pytest.mark.parametrize("literal", ["100-200", "100 or 200", "100 to 200", "10.5", "-100", "1,5"])
def test_unresolved_moq_is_not_a_model_choice_or_partial_integer(monkeypatch, model_available, literal):
    def extraction(*_):
        if not model_available:
            raise RuntimeError("controlled extraction unavailable")
        return {"unit_price": 4.5, "currency": "USD", "moq": 100,
                "confidence": 0.95}

    monkeypatch.setattr(parser, "llm_complete_json", extraction)
    reply = parser.parse_supplier_reply(f"Unit price USD 4.50; MOQ {literal} pcs; lead time 35 days.",
                                       project_id="case-unit", supplier_id="supplier-unit")
    assert reply.moq is None
    assert "moq" in reply.missing_info


def test_supplier_total_uses_actual_literal_moq_not_model_inflation(monkeypatch):
    monkeypatch.setenv("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "unit_price": 4.5, "currency": "USD", "moq": 10000, "confidence": 0.95})
    reply = parser.parse_supplier_reply("Unit price USD 4.50; MOQ 100 pcs; lead time 35 days.",
                                       project_id="case-unit", supplier_id="supplier-unit")
    options = generate_buyer_options(BuyerRequirement(project_id="case-unit", quantity=100),
                                     [reply], [], "case-unit")
    assert len(options) == 1
    assert options[0].quote.moq == 100
    assert options[0].quote.supplier_total == 450.0


@pytest.mark.parametrize("text,expected", [
    ("MOQ: 100 pcs", 100), ("MOQ=100pcs", 100), ("MOQ100 pieces", 100),
    ("MOQ 1,000 units", 1000), ("MOQ 100; MOQ 100", 100),
    ("MOQ 100; MOQ 200", None), ("MOQ 100 or 200; MOQ 100", None),
    ("MOQ not confirmed", None),
])
def test_moq_literal_controls_without_model(text, expected, monkeypatch):
    def unavailable(*_):
        raise RuntimeError("controlled extraction unavailable")
    monkeypatch.setattr(parser, "llm_complete_json", unavailable)
    reply = parser.parse_supplier_reply(text, project_id="case-unit")
    assert reply.moq == expected
    assert ("moq" in reply.missing_info) == (expected is None)


def test_semantic_minimum_without_literal_moq_keeps_existing_model_path(monkeypatch):
    monkeypatch.setattr(parser, "llm_complete_json", lambda *_: {
        "moq": 100, "currency": "USD", "confidence": 0.95})
    reply = parser.parse_supplier_reply("The minimum order is one hundred pieces.", project_id="case-unit")
    assert reply.moq == 100
