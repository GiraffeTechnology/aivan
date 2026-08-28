from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_critical_dependency_failure_records_zero_outbound_approval_and_progression_effects(
    monkeypatch,
):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "test-api-key")
    monkeypatch.setenv("AIVAN_TENANT_ID", "test-tenant")
    effects = {"outbound": 0, "approval": 0, "quote": 0, "progression": 0, "relay": 0}

    def failing_probe(*, correlation_id: str):
        return [
            module.DependencyProbeResult(
                dependency_id="giraffe-db",
                contract_version="aivan.dependency-probe.v1",
                criticality="critical",
                owner="DB",
                expected_version="v1",
                observed_version=None,
                status="unavailable",
                error_code="DEPENDENCY_UNAVAILABLE",
                correlation_id=correlation_id,
                checked_at_epoch=1.0,
                duration_seconds=0.01,
                stale_after_seconds=30.0,
            )
        ]

    monkeypatch.setattr(module, "run_dependency_probes", failing_probe)
    app = FastAPI()
    app.middleware("http")(module.dependency_side_effect_gate)

    for path, effect in (
        ("/invoke", "quote"),
        ("/api/drafts/d1/approve", "approval"),
        ("/api/projects/p1/run-gltg", "outbound"),
        ("/api/projects/p1/transition", "progression"),
        ("/api/relay/d1/confirm", "relay"),
    ):
        app.add_api_route(
            path,
            lambda effect=effect: effects.__setitem__(effect, effects[effect] + 1),
            methods=["POST"],
        )

    with TestClient(app) as client:
        for path in (
            "/invoke",
            "/api/drafts/d1/approve",
            "/api/projects/p1/run-gltg",
            "/api/projects/p1/transition",
            "/api/relay/d1/confirm",
        ):
            response = client.post(
                path,
                headers={
                    "X-AIVAN-Trace-ID": "corr-side-effect",
                    "X-AIVAN-API-Key": "test-api-key",
                    "X-AIVAN-Tenant-ID": "test-tenant",
                },
            )
            assert response.status_code == 503
            assert response.json() == {
                "error": "critical_dependency_unavailable",
                "correlation_id": "corr-side-effect",
            }

    assert effects == {"outbound": 0, "approval": 0, "quote": 0, "progression": 0, "relay": 0}
