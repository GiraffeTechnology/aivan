"""Tests for aiven.schemas.requirement — BuyerRequirement and MissingField."""
import pytest
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
