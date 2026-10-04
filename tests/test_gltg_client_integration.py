"""Optional live integration test against a running GLTG service.

Skipped unless RUN_GLTG_INTEGRATION_TESTS=1 and GLTG_API_BASE_URL points at a
reachable GLTG server (default http://localhost:8090).

    export GLTG_API_BASE_URL=http://localhost:8090
    export RUN_GLTG_INTEGRATION_TESTS=1
    pytest tests/test_gltg_client_integration.py
"""

from __future__ import annotations

import os

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

    est = client.simulate_lead_time_v2({
        "request_id": "aivan-live-consumer-quantiles",
        "tenant_id": os.environ["AIVAN_TENANT_ID"],
        "order": {"product_type": "apparel", "quantity": 10000},
        "supplier": {"supplier_id": "synthetic-live-numeric-only", "capacity_per_day": 800},
        "evidence": {"use_giraffe_db": False},
        "source_observation_ids": [],
    })
    assert est.ok, est.error
    # Actual authenticated v2 calculation only, not private DB acceptance.
    data = est.data
    quantiles = data["quantiles"]
    assert 0 <= quantiles["p50_days"] <= quantiles["p80_days"] <= quantiles["p90_days"]
    assert data["gltg_run_id"]
    assert "earliest_delivery_date" not in data


def test_live_missing_auth_does_not_call_provider(monkeypatch):
    client = GLTGClient()
    monkeypatch.delenv("GLTG_SERVICE_AUTH_SECRET", raising=False)
    result = client.simulate_lead_time_v2({"tenant_id": "synthetic-live-tenant", "order": {"quantity": 1}})
    assert result.ok is False
    assert result.status_code is None
    assert result.error == "GLTG_TRUSTED_PROFILE_MISSING"
