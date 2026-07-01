"""Tests for aiven.schemas.requirement — BuyerRequirement and MissingField."""
import pytest
from aivan.agents import requirement_agent
from aivan.agents.requirement_agent import structure_customer_requirement_with_llm
from aivan.schemas.requirement import BuyerRequirement, MissingField


def test_buyer_requirement_complete():
    req = BuyerRequirement(
        project_id="proj_001",
        product_type="men's shirt",
        quantity=10000,
        quantity_unit="pcs",
        category="apparel",
        fabric_material="100% cotton",
        gsm=180,
        color="white",
        size_ratio="S/M/L/XL=20/40/30/10",
        packaging="single poly bag",
        destination="Vancouver",
        target_unit_price=4.80,
        delivery_days=45,
        incoterms="DDP",
        missing_fields=[],
    )
    assert req.is_complete() is True


def test_buyer_requirement_missing_product_type_not_complete():
    req = BuyerRequirement(
        product_type="",
        quantity=10000,
        missing_fields=[],
    )
    assert req.is_complete() is False


def test_buyer_requirement_missing_quantity_not_complete():
    req = BuyerRequirement(
        product_type="shirt",
        quantity=None,
        missing_fields=[],
    )
    assert req.is_complete() is False


def test_buyer_requirement_with_missing_fields_not_complete():
    mf = MissingField(
        field_name="gsm",
        description="Fabric weight in grams per square metre",
        question="What is the fabric GSM?",
    )
    req = BuyerRequirement(
        product_type="shirt",
        quantity=10000,
        missing_fields=[mf],
    )
    assert req.is_complete() is False


def test_missing_field_model():
    mf = MissingField(
        field_name="size_ratio",
        description="Size breakdown",
        question="What is the size ratio?",
    )
    assert mf.field_name == "size_ratio"
    assert mf.description == "Size breakdown"
    assert mf.question == "What is the size ratio?"


def test_buyer_requirement_defaults():
    req = BuyerRequirement()
    assert req.target_currency == "USD"
    assert req.quantity_unit == "pcs"
    assert req.missing_fields == []
    assert req.language == "en"


def test_buyer_requirement_extra_field():
    req = BuyerRequirement(
        product_type="shirt",
        quantity=5000,
        extra={"custom_key": "custom_value"},
    )
    assert req.extra["custom_key"] == "custom_value"


def test_non_english_requirement_hard_fields_do_not_trust_translation(monkeypatch):
    calls = []

    def fake_llm(task, system_prompt, user_prompt, schema_hint=None, temperature=0.0):
        calls.append((task, user_prompt))
        if task == "requirement_translation":
            return {
                "translated_text": "Quote for 500 plaid shirts, deliver to Tokyo in 45 days, high quality. Please give me a preliminary quotation.",
                "confidence": 0.95,
            }
        if task == "requirement_structuring":
            assert "deliver to Tokyo" in user_prompt
            return {
                "category": "apparel",
                "product_type": "shirt",
                "quantity": 500,
                "delivery_days": 45,
                "destination": None,
                "confidence": 0.7,
                "language": "en",
            }
        raise AssertionError(task)

    monkeypatch.setattr(requirement_agent, "llm_complete_json", fake_llm)

    req = structure_customer_requirement_with_llm("询价5000件格子衬衫，45天交东京，高品质，请给我一个初步报价")

    assert [call[0] for call in calls] == ["requirement_translation", "requirement_structuring"]
    assert req.quantity == 5000
    assert req.destination == "Tokyo"
    assert req.delivery_days == 45
    assert req.language == "zh"
    assert req.extra["translated_text"].startswith("Quote for 500")


def test_english_osaka_requirement_coerces_llm_list_notes(monkeypatch):
    calls = []

    def fake_llm(task, system_prompt, user_prompt, schema_hint=None, temperature=0.0):
        calls.append(task)
        if task == "requirement_structuring":
            return {
                "category": "apparel",
                "product_type": "shirt",
                "quantity": 5000,
                "delivery_days": 45,
                "destination": None,
                "notes": ["Order: 5000 plaid shirts to Osaka within 45 days"],
                "confidence": 0.7,
                "language": "en",
            }
        raise AssertionError(task)

    monkeypatch.setattr(requirement_agent, "llm_complete_json", fake_llm)

    req = structure_customer_requirement_with_llm(
        "Inquiry: Order 5000 plaid shirts, to be shipped to Osaka within 45 days."
    )

    assert calls == ["requirement_structuring"]
    assert req.quantity == 5000
    assert req.destination == "Osaka"
    assert req.delivery_days == 45
    assert req.notes == "Order: 5000 plaid shirts to Osaka within 45 days"
