"""Optional live integration test against a running GLTG service.

Skipped unless RUN_GLTG_INTEGRATION_TESTS=1 and GLTG_API_BASE_URL points at a
reachable GLTG server (default http://localhost:8090).

    export GLTG_API_BASE_URL=http://localhost:8090
    export RUN_GLTG_INTEGRATION_TESTS=1
    pytest tests/test_gltg_client_integration.py
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from aivan.integrations.gltg_client import GLTGClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GLTG_INTEGRATION_TESTS") != "1",
    reason="set RUN_GLTG_INTEGRATION_TESTS=1 to run against a live GLTG server",
)


def test_live_health_and_estimate():
    client = GLTGClient()
    health = client.health()
    assert health.ok, health.error
    assert health.data["service"] == "gltg"

    est = client.estimate_lead_time(
        order={"product_type": "apparel", "quantity": 10000, "evaluation_date": "2026-10-03"},
        suppliers=[
            {
                "supplier_id": "M1",
                "name": "Supplier M1",
                "capacity_per_day": 800,
                "material_ready_days": 5,
                "production_days": 14,
                "qc_days": 2,
                "logistics_days": 7,
                "confidence": 0.8,
            }
        ],
    )
    assert est.ok, est.error
    # The current v1 adapter reports graph-engine dates, not the old sum of
    # supplier stage hints. Verify its documented date/quantile mapping.
    data = est.data
    anchor = date(2026, 10, 3)
    duration = lambda key: (date.fromisoformat(data[key]) - anchor).days
    assert data["estimated_lead_time_days"] == duration("committable_date")
    assert data["p50_days"] == duration("earliest_delivery_date")
    assert data["p80_days"] == duration("most_likely_date")
    assert data["p90_days"] == data["estimated_lead_time_days"]
    assert 0 <= data["p50_days"] <= data["p80_days"] <= data["p90_days"]
    assert data["selected_supplier_id"] == "M1"
    assert data["calculation_trace"][0]["supplier_id"] == "M1"
    assert data["calculation_trace"][0]["total_lead_time_days"] == data["estimated_lead_time_days"]
    assert est.data["feasible"] is True


def test_live_zero_supplier_does_not_crash():
    client = GLTGClient()
    est = client.estimate_lead_time(order={"quantity": 1000}, suppliers=[])
    assert est.ok, est.error
    assert est.data["feasible"] is False
    assert any(w["code"] == "NO_SUPPLIERS" for w in est.data["warnings"])
