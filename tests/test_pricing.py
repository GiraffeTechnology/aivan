"""Tests for aiven.pricing.quote_calculator."""
import pytest
from aivan.pricing.quote_calculator import calculate_buyer_quote, calculate_supplier_total


# --- calculate_supplier_total ---

def test_supplier_total_basic():
    result = calculate_supplier_total(unit_price=5.0, quantity=1000)
    assert result["supplier_total"] == 5000.0
    assert result["quantity_billed"] == 1000


def test_supplier_total_moq_enforcement():
    """Quantity below MOQ → billed at MOQ."""
    result = calculate_supplier_total(unit_price=5.0, quantity=100, moq=500)
    assert result["quantity_billed"] == 500
    assert len(result["warnings"]) > 0
    assert "below" in result["warnings"][0].lower() or "moq" in result["warnings"][0].lower()


def test_supplier_total_above_moq_no_warning():
    result = calculate_supplier_total(unit_price=5.0, quantity=1000, moq=500)
    assert result["quantity_billed"] == 1000
    assert result["warnings"] == []


# --- calculate_buyer_quote ---

def test_buyer_quote_returns_dict():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000)
    assert isinstance(result, dict)


def test_buyer_quote_margin_formula():
    """buyer_total = cost / (1 - margin_rate)."""
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, margin_rate=0.20)
    cost = result["supplier_total"]
    expected_buyer_total = cost / (1 - 0.20)
    assert abs(result["buyer_total"] - expected_buyer_total) < 0.02


def test_buyer_unit_price_greater_than_supplier_price():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, margin_rate=0.15)
    assert result["buyer_unit_price"] > result["unit_price"]


def test_buyer_quote_zero_margin():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, margin_rate=0.0)
    assert result["buyer_total"] == result["supplier_total"]
    assert result["margin_amount"] == 0.0


def test_buyer_quote_moq_warning():
    result = calculate_buyer_quote(unit_price=5.0, quantity=100, moq=500)
    assert len(result["warnings"]) > 0


def test_buyer_quote_calculation_trace_present():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000)
    assert isinstance(result["calculation_trace"], list)
    assert len(result["calculation_trace"]) > 0


def test_buyer_quote_currency_propagated():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, currency="CNY")
    assert result["currency"] == "CNY"


def test_buyer_quote_supplier_id_propagated():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, supplier_id="sup_001")
    assert result["supplier_id"] == "sup_001"


def test_buyer_quote_international_logistics_included():
    result = calculate_buyer_quote(unit_price=5.0, quantity=1000, international_logistics_fee=200.0, margin_rate=0.0)
    assert result["buyer_total"] == result["supplier_total"] + 200.0
