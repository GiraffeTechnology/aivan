"""Tests for aiven.schemas.requirement — BuyerRequirement and MissingField."""
import pytest
from aivan.agents import requirement_agent
from aivan.agents.requirement_agent import (
    _deterministic_parse,
    structure_customer_requirement_with_llm,
)
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


def test_deterministic_parse_does_not_canonicalize_destination():
    # No business-semantic hardcoding: the deterministic parser must NOT map a
    # place surface form to a canonical destination (PRD §2.1/§2.2). Destination
    # canonicalization requires an authoritative source (language-skill /
    # resolver / human confirmation), never a local alias table.
    assert "destination" not in _deterministic_parse("交东京")
    assert "destination" not in _deterministic_parse("shipped to Osaka")


def test_deterministic_parse_does_not_canonicalize_non_english_business_semantics():
    parsed = _deterministic_parse(
        "询价 5000 件格子衬衫，白色纯棉，高品质，找熟悉供应商，45天交东京"
    )

    for forbidden_field in (
        "product_type",
        "category",
        "destination",
        "fabric_material",
        "quality_level",
        "supplier_scope",
        "supplier_capability",
    ):
        assert forbidden_field not in parsed


def test_deterministic_parse_keeps_numeric_raw_evidence():
    # Numeric evidence (quantity, days) is preserved; it is not business-semantic
    # canonicalization.
    parsed = _deterministic_parse("询价 5000 件，45天交货")
    assert parsed["quantity"] == 5000
    assert parsed["delivery_days"] == 45


def test_non_english_rfq_without_language_skill_blocks_all_local_extraction(monkeypatch):
    # P0 internal-language rule: product workflow must not extract business
    # fields from raw non-English text. language-skill must translate to
    # canonical English and structure the RFQ first.
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    monkeypatch.setattr(
        requirement_agent,
        "llm_complete_json",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected AIVAN LLM call")),
    )

    req = structure_customer_requirement_with_llm(
        "询价 5000 件格子衬衫，45天交东京，高品质，请给我一个初步报价"
    )

    from aivan.execution.safety import evaluate_requirement_readiness

    assert req.language == "zh"
    assert req.quantity is None
    assert req.delivery_days is None
    assert req.product_type == ""
    assert req.destination == ""  # never guessed from raw text
    assert req.extra["non_english_local_extraction_blocked"] == "language_skill_required"
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "destination" in gate.missing_fields


def test_deterministic_fallback_english_osaka_blocks_on_destination(monkeypatch):
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    monkeypatch.setattr(requirement_agent, "llm_complete_json", lambda *a, **k: {})

    req = structure_customer_requirement_with_llm(
        "Inquiry: Order 5000 plaid shirts, to be shipped to Osaka within 45 days."
    )

    from aivan.execution.safety import evaluate_requirement_readiness

    assert req.delivery_days == 45
    assert req.destination == ""
    gate = evaluate_requirement_readiness(req)
    assert not gate.ready
    assert "destination" in gate.missing_fields
