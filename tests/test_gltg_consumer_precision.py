"""Consumer-mapping unit tests; synthetic provider DTOs, not live GLTG evidence."""
from copy import deepcopy

import pytest

from aivan.integrations.gltg import GLTGClient, GLTGUnavailableError
from aivan.schemas.requirement import BuyerRequirement
from aivan.schemas.response import SupplierReply
from aivan.schemas.rfq import RFQStrategy


def requirement():
    return BuyerRequirement(project_id="precision", quantity=100, destination="Synthetic destination", delivery_days=12)


def payload():
    return {
        "p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75,
        "estimated_lead_time_days": 12.5, "minimum_feasible_days": 8.125,
        "feasible": False, "risk_level": "medium",
        "critical_path": ["provider-stage"],
        "calculation_trace": [{"material_ready_days": 0.25, "capacity_adjusted_production_days": 3.75,
                               "qc_days": 0.5, "logistics_days": 1.125}],
    }


def facade(monkeypatch, data):
    client = GLTGClient()
    # Isolate mapping only. Production code receives no fallback or stub path.
    monkeypatch.setattr(client, "_estimate", lambda **kwargs: deepcopy(data))
    return client


def test_fractional_quantiles_calculated_days_and_components_are_preserved(monkeypatch):
    result = facade(monkeypatch, payload()).estimate_for_requirement(requirement())
    assert (result.p50_days, result.p80_days, result.p90_days) == (10.25, 12.5, 14.75)
    assert result.calculated_lead_time_days == 12.5
    assert result.earliest_possible_days == 8.125
    assert {component.name: component.days for component in result.components} == {
        "material_ready": 0.25, "production": 3.75, "qc": 0.5, "logistics": 1.125}
    assert result.critical_path == ["provider-stage"]


def test_fractional_confidence_is_not_truncated_across_deadline_cutoff(monkeypatch):
    result = facade(monkeypatch, payload()).simulate(requirement(), RFQStrategy(), supplier_count=2)
    assert result.selected_confidence_days == 12.5
    assert result.known_suppliers_first_feasibility == "tight"


def test_missing_earliest_is_not_invented_from_expected_lead_time(monkeypatch):
    data = payload(); del data["minimum_feasible_days"]
    client = facade(monkeypatch, data)
    assert client.estimate_for_requirement(requirement()).earliest_possible_days is None
    assert client.simulate(requirement(), RFQStrategy(), supplier_count=2).minimum_feasible_days is None


def test_explicit_zero_minimum_is_not_replaced_by_truthiness(monkeypatch):
    data = payload(); data["minimum_feasible_days"] = 0
    client = facade(monkeypatch, data)
    assert client.estimate_for_requirement(requirement()).earliest_possible_days == 0
    assert client.simulate(requirement(), RFQStrategy(), supplier_count=2).minimum_feasible_days == 0


def test_missing_components_and_critical_path_are_not_fabricated(monkeypatch):
    data = payload(); data.pop("calculation_trace"); data.pop("critical_path")
    result = facade(monkeypatch, data).estimate_for_requirement(requirement())
    assert result.components == []
    assert result.critical_path == []


def test_v2_quantile_is_not_evidence_of_an_earliest_delivery():
    result = GLTGClient._normalize_v2_result({"ok": True, "quantiles": {"p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75},
                                            "risk": {"selected_confidence_days": 12.5}})
    assert result.get("minimum_feasible_days") is None


def test_v2_selected_zero_confidence_is_preserved():
    result = GLTGClient._normalize_v2_result({"ok": True, "quantiles": {"p50_days": 0, "p80_days": 1.25, "p90_days": 2.5},
                                            "risk": {"selected_confidence_days": 0}})
    assert result["estimated_lead_time_days"] == 0


@pytest.mark.parametrize("value", [None, False, True])
def test_unknown_feasibility_does_not_become_false(monkeypatch, value):
    data = payload(); data["feasible"] = value
    assert facade(monkeypatch, data).estimate_for_requirement(requirement()).deadline_feasible is value


@pytest.mark.parametrize("value", ["false", "true", "", 0, 1, [], {}])
def test_malformed_feasibility_does_not_become_true(monkeypatch, value):
    data = payload(); data["feasible"] = value
    with pytest.raises(GLTGUnavailableError):
        facade(monkeypatch, data).estimate_for_requirement(requirement())


def test_supplier_stated_fractional_days_are_not_coerced_to_integer():
    reply = SupplierReply(project_id="precision", supplier_id="synthetic", raw_text="Lead time 12.5 days", lead_time_days=12.5)
    assert reply.lead_time_days == 12.5


def test_supplier_fallback_parser_keeps_fractional_day_statement(monkeypatch):
    from aivan.agents import supplier_response_agent
    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic parser dependency unavailable")
    monkeypatch.setattr(supplier_response_agent, "llm_complete_json", unavailable)
    result = supplier_response_agent.parse_supplier_reply("Lead time: 12.5 days", "precision", supplier_id="synthetic")
    assert result.lead_time_days == 12.5
