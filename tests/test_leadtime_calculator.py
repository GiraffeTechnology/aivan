"""Tests for aiven.leadtime.calculator — calculate_apparel_leadtime()."""
import pytest
from aivan.leadtime.calculator import calculate_apparel_leadtime


def test_basic_sea_routing_returns_estimate():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert result is not None
    assert result.calculated_lead_time_days > 0


def test_sea_routing_vancouver_base_total():
    """Sea transit for Vancouver is 18 days; total should be well above 55."""
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert result.calculated_lead_time_days >= 55


def test_air_routing_shorter_transit():
    sea = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    air = calculate_apparel_leadtime(10000, 500, "Vancouver", "air")
    # Air transit (3 days) vs sea transit (18 days) → air total should be lower
    assert air.calculated_lead_time_days < sea.calculated_lead_time_days


def test_air_routing_vancouver_transit_days():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "air")
    transit_comp = next(c for c in result.components if c.name == "international_transit")
    assert transit_comp.days == 3


def test_sea_routing_vancouver_transit_days():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    transit_comp = next(c for c in result.components if c.name == "international_transit")
    assert transit_comp.days == 18


def test_p50_p80_p90_ordering():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert result.p50_days <= result.p80_days <= result.p90_days


def test_deadline_feasible_true_for_generous_deadline():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea", deadline_days=200)
    assert result.deadline_feasible is True


def test_deadline_feasible_false_for_impossible_deadline():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea", deadline_days=1)
    assert result.deadline_feasible is False


def test_deadline_days_none_leaves_feasible_unknown():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea", deadline_days=None)
    assert result.deadline_feasible is None
    assert result.deadline_risk_level == "unknown"


def test_quantity_affects_sewing_days():
    small = calculate_apparel_leadtime(100, 500, "Vancouver", "sea")
    large = calculate_apparel_leadtime(50000, 500, "Vancouver", "sea")
    assert large.calculated_lead_time_days > small.calculated_lead_time_days


def test_estimate_has_estimate_id():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert result.estimate_id and len(result.estimate_id) > 0


def test_components_list_not_empty():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert len(result.components) > 0


def test_risk_buffer_days():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert result.risk_buffer_days == 5


def test_missing_inputs_when_default_capacity():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea")
    assert "actual_daily_capacity" in result.missing_inputs


def test_project_id_propagated():
    result = calculate_apparel_leadtime(10000, 500, "Vancouver", "sea", project_id="proj_test")
    assert result.project_id == "proj_test"
