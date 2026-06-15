"""Tests for aiven.agents.buyer_option_agent — generate_buyer_options()."""
import os
import pytest

os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("AIVAN_HIDE_SUPPLIER_IDENTITY_FROM_BUYER", "false")
os.environ.setdefault("AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER", "false")

from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.leadtime.calculator import calculate_apparel_leadtime


def _make_requirement() -> BuyerRequirement:
    return BuyerRequirement(
        project_id="proj_test",
        product_type="men's shirt",
        category="apparel",
        quantity=10000,
        destination="Vancouver",
        target_unit_price=5.0,
        delivery_days=60,
        logistics_preference="sea",
    )


def _make_reply(supplier_id: str = "sup_001", unit_price: float = 4.50) -> SupplierReply:
    return SupplierReply(
        project_id="proj_test",
        supplier_id=supplier_id,
        raw_text="We can supply at 4.50/pc",
        unit_price=unit_price,
        currency="USD",
        moq=5000,
        lead_time_days=35,
    )


def _make_lead_time(supplier_id: str = "sup_001") -> LeadTimeEstimate:
    return calculate_apparel_leadtime(
        quantity=10000,
        daily_capacity=500,
        destination="Vancouver",
        logistics_preference="sea",
        supplier_id=supplier_id,
        project_id="proj_test",
        deadline_days=60,
    )


def test_generate_buyer_options_returns_list():
    req = _make_requirement()
    reply = _make_reply()
    lt = _make_lead_time()
    options = generate_buyer_options(req, [reply], [lt], "proj_test")
    assert isinstance(options, list)


def test_generate_buyer_options_at_least_one_option():
    req = _make_requirement()
    reply = _make_reply()
    lt = _make_lead_time()
    options = generate_buyer_options(req, [reply], [lt], "proj_test")
    assert len(options) >= 1


def test_generate_buyer_options_empty_replies_returns_empty():
    req = _make_requirement()
    options = generate_buyer_options(req, [], [], "proj_test")
    assert options == []


def test_generate_buyer_options_nil_price_skipped():
    req = _make_requirement()
    reply = SupplierReply(project_id="proj_test", supplier_id="sup_001", raw_text="no price", unit_price=None)
    options = generate_buyer_options(req, [reply], [], "proj_test")
    assert options == []


def test_option_has_required_fields():
    req = _make_requirement()
    reply = _make_reply()
    lt = _make_lead_time()
    options = generate_buyer_options(req, [reply], [lt], "proj_test")
    opt = options[0]
    assert opt.option_id is not None
    assert opt.project_id == "proj_test"
    assert opt.option_label != ""
    assert opt.option_type != ""


def test_option_has_quote():
    req = _make_requirement()
    reply = _make_reply()
    lt = _make_lead_time()
    options = generate_buyer_options(req, [reply], [lt], "proj_test")
    assert options[0].quote is not None


def test_option_buyer_unit_price_greater_than_zero():
    req = _make_requirement()
    reply = _make_reply()
    lt = _make_lead_time()
    options = generate_buyer_options(req, [reply], [lt], "proj_test")
    assert options[0].quote.buyer_unit_price > 0


def test_multiple_replies_can_produce_multiple_options():
    req = _make_requirement()
    replies = [
        _make_reply("sup_001", 4.50),
        _make_reply("sup_002", 4.20),
        _make_reply("sup_003", 4.80),
    ]
    lts = [
        calculate_apparel_leadtime(10000, 500, "Vancouver", "sea", supplier_id="sup_001", project_id="proj_test", deadline_days=60),
        calculate_apparel_leadtime(10000, 300, "Vancouver", "sea", supplier_id="sup_002", project_id="proj_test", deadline_days=60),
        calculate_apparel_leadtime(10000, 700, "Vancouver", "sea", supplier_id="sup_003", project_id="proj_test", deadline_days=60),
    ]
    options = generate_buyer_options(req, replies, lts, "proj_test")
    assert len(options) >= 1
    # With 3 distinct suppliers, we can get up to 3 options
    assert len(options) <= 3
