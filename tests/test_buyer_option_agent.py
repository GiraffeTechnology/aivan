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
from aivan.integrations.gltg import GLTGClient as _GLTGFacade


def _gltg_lead_time(supplier_id: str, capacity: int) -> LeadTimeEstimate:
    """Build a LeadTimeEstimate via the standalone GLTG facade (mocked in tests)."""
    req = _make_requirement()
    reply = SupplierReply(
        project_id="proj_test",
        supplier_id=supplier_id,
        raw_text="capacity",
        unit_price=4.5,
        currency="USD",
        moq=5000,
        lead_time_days=35,
        capacity_per_day=capacity,
    )
    return _GLTGFacade().estimate_for_requirement(req, supplier_reply=reply, supplier_id=supplier_id)


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
    return _gltg_lead_time(supplier_id, capacity=500)


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
        _gltg_lead_time("sup_001", 500),
        _gltg_lead_time("sup_002", 300),
        _gltg_lead_time("sup_003", 700),
    ]
    options = generate_buyer_options(req, replies, lts, "proj_test")
    assert len(options) >= 1
    # With 3 distinct suppliers, we can get up to 3 options
    assert len(options) <= 3


def test_mixed_currencies_are_not_ranked_as_lowest_cost():
    req = _make_requirement()
    replies = [
        SupplierReply(
            project_id="proj_test",
            supplier_id="sup_usd",
            raw_text="USD quote",
            unit_price=4.0,
            currency="USD",
            lead_time_days=45,
        ),
        SupplierReply(
            project_id="proj_test",
            supplier_id="sup_eur",
            raw_text="EUR quote",
            unit_price=3.0,
            currency="EUR",
            lead_time_days=20,
        ),
    ]
    lead_times = [
        LeadTimeEstimate(
            estimate_id="lt_usd",
            project_id="proj_test",
            supplier_id="sup_usd",
            category="apparel",
            calculated_lead_time_days=45,
            earliest_possible_days=40,
            expected_days=45,
            conservative_days=50,
            p50_days=45,
            p80_days=50,
            p90_days=55,
            risk_buffer_days=5,
        ),
        LeadTimeEstimate(
            estimate_id="lt_eur",
            project_id="proj_test",
            supplier_id="sup_eur",
            category="apparel",
            calculated_lead_time_days=20,
            earliest_possible_days=18,
            expected_days=20,
            conservative_days=24,
            p50_days=20,
            p80_days=24,
            p90_days=28,
            risk_buffer_days=4,
        ),
    ]

    options = generate_buyer_options(req, replies, lead_times, "proj_test")

    assert all(option.option_type != "lowest_cost" for option in options)
    assert all(
        any("not directly comparable" in warning for warning in option.warnings)
        for option in options
    )


@pytest.mark.parametrize(
    ("currencies", "quantity_unit"),
    [
        (("USD", ""), "pcs"),
        (("USD", "USD"), "kg"),
    ],
)
def test_incomplete_quote_basis_is_not_ranked_as_lowest_cost(
    currencies, quantity_unit
):
    req = _make_requirement().model_copy(update={"quantity_unit": quantity_unit})
    replies = [
        SupplierReply(
            project_id="proj_test",
            supplier_id="sup_a",
            raw_text="first quote",
            unit_price=4.0,
            currency=currencies[0],
        ),
        SupplierReply(
            project_id="proj_test",
            supplier_id="sup_b",
            raw_text="second quote",
            unit_price=3.0,
            currency=currencies[1],
        ),
    ]

    options = generate_buyer_options(req, replies, [], "proj_test")

    assert all(option.option_type != "lowest_cost" for option in options)
    assert all(
        any("not directly comparable" in warning for warning in option.warnings)
        for option in options
    )


def test_duplicate_supplier_revision_produces_one_current_business_option():
    req = _make_requirement()
    old = SupplierReply(
        project_id="proj_test",
        supplier_id="sup_a",
        raw_text="old quote",
        unit_price=5.0,
        currency="USD",
        received_at="2026-09-30T09:00:00Z",
    )
    current = old.model_copy(
        update={
            "raw_text": "revised quote",
            "unit_price": 4.5,
            "received_at": "2026-09-30T10:00:00Z",
        }
    )

    options = generate_buyer_options(req, [old, current], [], "proj_test")

    assert len(options) == 1
    assert options[0].supplier_id == "sup_a"
    assert options[0].quote is not None
    assert options[0].quote.unit_price == 4.5
    assert options[0].option_type == "lowest_cost"


def test_missing_lead_time_does_not_claim_fastest_or_reliability_history():
    req = _make_requirement()
    replies = [
        SupplierReply(
            project_id="proj_test",
            supplier_id="sup_a",
            raw_text="quote",
            unit_price=4.5,
            currency="USD",
        )
    ]

    options = generate_buyer_options(req, replies, [], "proj_test")

    assert all(option.option_type != "fastest" for option in options)
    assert all("strong track record" not in option.reasoning for option in options)
