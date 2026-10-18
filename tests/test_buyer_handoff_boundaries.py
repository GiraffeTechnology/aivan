"""Direct new buyer-selection branch coverage; no external calculations."""
from aivan.agents.buyer_option_agent import generate_buyer_options
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.leadtime import LeadTimeEstimate
from aivan.execution.source_quote import source_quote_reference


def test_zero_price_third_candidate_and_unverified_risk_remain_honest(monkeypatch):
    monkeypatch.setenv('AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER', 'false')
    requirement = BuyerRequirement(project_id='fixture', quantity=100, quantity_unit='pcs')
    replies = [SupplierReply(project_id='fixture', supplier_id=f'supplier-{i}', raw_text=f'quote-{i}',
        unit_price=price, currency='GBP', risks=['unverified note']) for i, price in enumerate([0.0, 2.0, 3.0])]
    leads = [LeadTimeEstimate(estimate_id=f'e-{i}', project_id='fixture', supplier_id=f'supplier-{i}',
        category='fixture', calculated_lead_time_days=days, expected_days=days, conservative_days=days,
        p50_days=days, p80_days=days, p90_days=days, risk_buffer_days=0) for i, days in enumerate([1.5, 2.5, 3.5])]
    options = generate_buyer_options(requirement, replies, leads, 'fixture')
    assert len(options) == 3
    assert {option.supplier_id for option in options} == {reply.supplier_id for reply in replies}
    zero = next(option for option in options if option.supplier_id == 'supplier-0')
    assert zero.quote.unit_price == 0.0
    assert zero.quote.currency == 'GBP'
    assert all(option.risk_level == 'unknown' for option in options)
    assert all(option.source_quote_reference == source_quote_reference(replies[int(option.supplier_id[-1])]) for option in options)
    assert 'Best Value' not in options[1].option_label


def test_mixed_currencies_never_claim_lowest_price(monkeypatch):
    monkeypatch.setenv('AIVAN_HIDE_SUPPLIER_PRICE_FROM_BUYER', 'false')
    replies = [SupplierReply(project_id='fixture', supplier_id=f's-{i}', raw_text=f'q-{i}',
        unit_price=price, currency=currency) for i, (price, currency) in enumerate([(1.0, 'GBP'), (0.5, 'USD'), (2.0, '')])]
    options = generate_buyer_options(BuyerRequirement(project_id='fixture', quantity=100, quantity_unit='pcs'), replies, [], 'fixture')
    assert len(options) == 3
    assert all(option.option_type != 'lowest_cost' for option in options)
    assert {option.quote.currency for option in options} == {'GBP', 'USD', ''}
    assert all(any('not directly comparable' in warning for warning in option.warnings) for option in options)
