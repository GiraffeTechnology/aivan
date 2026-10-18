"""Synthetic consumer mapping checks, not live service acceptance."""
from copy import deepcopy

import pytest

from aivan.integrations.gltg import GLTGClient, GLTGUnavailableError
from aivan.schemas.requirement import BuyerRequirement


@pytest.mark.parametrize("value", [None, False, True])
def test_typed_or_unknown_feasibility_survives_mapping(monkeypatch, value):
    client = GLTGClient()
    data = {"p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75,
            "estimated_lead_time_days": 12.5, "feasible": value}
    monkeypatch.setattr(client, "_estimate", lambda **kwargs: deepcopy(data))
    result = client.estimate_for_requirement(BuyerRequirement(quantity=100, delivery_days=12))
    assert result.deadline_feasible is value
    assert result.p80_days == 12.5


@pytest.mark.parametrize("value", ["false", "true", "", 0, 1, [], {}])
def test_invalid_feasibility_is_rejected_not_truth_coerced(monkeypatch, value):
    client = GLTGClient()
    data = {"p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75,
            "estimated_lead_time_days": 12.5, "feasible": value}
    monkeypatch.setattr(client, "_estimate", lambda **kwargs: deepcopy(data))
    with pytest.raises(GLTGUnavailableError, match="GLTG_RESPONSE_INVALID"):
        client.estimate_for_requirement(BuyerRequirement(quantity=100, delivery_days=12))


@pytest.mark.parametrize("value", [None, False, True])
def test_v2_risk_roundtrip_preserves_unknown_and_boolean(monkeypatch, value):
    data = GLTGClient._normalize_v2_result({
        "ok": True, "quantiles": {"p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75},
        "risk": {"deadline_feasible": value, "selected_confidence_days": 12.5}})
    client = GLTGClient()
    monkeypatch.setattr(client, "_estimate", lambda **kwargs: deepcopy(data))
    result = client.estimate_for_requirement(BuyerRequirement(quantity=100, delivery_days=12))
    assert result.deadline_feasible is value


def test_no_deadline_does_not_manufacture_a_feasibility_decision(monkeypatch):
    client = GLTGClient()
    data = {"p50_days": 10.25, "p80_days": 12.5, "p90_days": 14.75,
            "estimated_lead_time_days": 12.5, "feasible": True}
    monkeypatch.setattr(client, "_estimate", lambda **kwargs: deepcopy(data))
    assert client.estimate_for_requirement(BuyerRequirement(quantity=100)).deadline_feasible is None
