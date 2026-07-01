"""Tests for aiven.schemas.requirement — BuyerRequirement and MissingField."""
import pathlib
import re

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


def test_aivan_does_not_hardcode_destination_aliases():
    # Architectural guard: AIVAN production code must not own a destination
    # dictionary. Canonical destinations come from giraffe-language-skill (or a
    # future shared resolver), never from an AIVAN-local alias table.
    src_root = pathlib.Path(__file__).resolve().parents[1] / "src" / "aivan"
    offenders = []
    for path in src_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"CITY_ALIASES|PORT_ALIASES|DESTINATION_ALIASES", text):
            offenders.append(str(path))
        # No hardcoded surface->canonical destination mapping (e.g. 东京 -> Tokyo).
        if re.search(r"东京.*Tokyo|大阪.*Osaka|Tokyo.*东京|Osaka.*大阪", text):
            offenders.append(str(path))
    assert not offenders, f"AIVAN production code hardcodes destination aliases: {offenders}"


def test_deterministic_parse_does_not_canonicalize_destination():
    # The deterministic fallback may capture other hard fields but must NOT set a
    # canonical destination from raw text.
    parsed = _deterministic_parse("询价 5000 件格子衬衫，45天交东京，高品质")
    assert "destination" not in parsed
    assert parsed.get("delivery_days") == 45


def test_language_skill_disabled_preserves_raw_destination_but_requires_confirmation(monkeypatch):
    # Private-domain mode: language skill off + LLM API off. AIVAN must preserve
    # the raw destination evidence, keep the canonical destination unresolved, and
    # ask for confirmation instead of guessing — without any LLM call.
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    monkeypatch.setenv("AIVAN_LLM_API_ENABLED", "false")
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "disabled")

    from aivan.llm import gateway

    def _fail_llm(*a, **k):
        raise AssertionError("LLM API must not be called in private-domain mode")

    monkeypatch.setattr(gateway, "get_provider", _fail_llm)

    req = structure_customer_requirement_with_llm(
        "询价 5000 件格子衬衫，45天交东京，高品质，请给我一个初步报价"
    )

    assert req.language == "zh"
    assert not req.destination  # not canonicalized by AIVAN
    assert "东京" in (req.extra.get("destination_raw") or "")
    assert req.extra.get("destination_canonical") is None
    assert req.extra.get("destination_source") == "raw_text_only"
    assert any(mf.field_name == "destination" for mf in req.missing_fields)
    assert req.delivery_days == 45
