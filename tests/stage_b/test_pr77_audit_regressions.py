from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient


def _giraffe_db_spec(module):
    return next(
        spec
        for spec in module.required_dependency_specs()
        if spec.dependency_id == "giraffe-db"
    )


def test_giraffe_db_probe_accepts_fixed_provider_response_shapes(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    contract = importlib.import_module("aivan.gpm.persistence_contract")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "0.2.0")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    monkeypatch.setenv("AIVAN_DEPENDENCY_PROBE_TENANT_ID", "tenant-probe")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/healthz":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "service": "giraffe-db",
                    "schema_version": "0.2.0",
                },
            )
        if request.url.path == "/api/data/schema-version":
            return httpx.Response(200, json={"schema_version": "0.2.0"})
        return httpx.Response(404)

    result = module.run_dependency_probes(
        correlation_id="corr-db-probe",
        specs=(_giraffe_db_spec(module),),
        transport=httpx.MockTransport(handler),
    )[0]

    assert result.ready is True
    assert [request.url.path for request in captured] == [
        "/healthz",
        "/api/data/schema-version",
    ]
    for request in captured:
        headers = request.headers
        assert headers["X-Service-Auth"] == "service-secret"
        assert headers["X-Service-Tenant-ID"] == "tenant-probe"
        assert (
            headers["X-GPM-Contract-Version"]
            == contract.GPM_PERSISTENCE_CONTRACT_VERSION
        )
        assert headers["X-AIVAN-Correlation-ID"] == "corr-db-probe"
        assert headers["X-AIVAN-Trace-ID"] == "corr-db-probe"


@pytest.mark.parametrize(
    ("health_status", "schema_version", "expected_status", "expected_error"),
    [
        ("down", "0.2.0", "unavailable", "DEPENDENCY_NOT_READY"),
        ("ok", "0.1.0", "incompatible", "DEPENDENCY_VERSION_MISMATCH"),
    ],
)
def test_giraffe_db_probe_fails_closed_for_health_or_version_mismatch(
    monkeypatch,
    health_status,
    schema_version,
    expected_status,
    expected_error,
):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "0.2.0")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    monkeypatch.setenv("AIVAN_DEPENDENCY_PROBE_TENANT_ID", "tenant-probe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": health_status})
        if request.url.path == "/api/data/schema-version":
            return httpx.Response(200, json={"schema_version": schema_version})
        return httpx.Response(404)

    result = module.run_dependency_probes(
        correlation_id="corr-db-failure",
        specs=(_giraffe_db_spec(module),),
        transport=httpx.MockTransport(handler),
    )[0]
    assert result.ready is False
    assert result.status == expected_status
    assert result.error_code == expected_error


def test_giraffe_db_probe_rejects_wrong_service_auth(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "0.2.0")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "wrong-secret")
    monkeypatch.setenv("AIVAN_DEPENDENCY_PROBE_TENANT_ID", "tenant-probe")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("X-Service-Auth") != "accepted-secret":
            return httpx.Response(403, json={"detail": "forbidden"})
        return httpx.Response(200, json={"status": "ok"})

    result = module.run_dependency_probes(
        correlation_id="corr-db-wrong-auth",
        specs=(_giraffe_db_spec(module),),
        transport=httpx.MockTransport(handler),
    )[0]
    assert result.ready is False
    assert result.status == "unavailable"
    assert result.error_code == "DEPENDENCY_UNAVAILABLE"


def test_giraffe_db_probe_without_service_auth_makes_zero_requests(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "0.2.0")
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)
    monkeypatch.setenv("AIVAN_DEPENDENCY_PROBE_TENANT_ID", "tenant-probe")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "ok"})

    result = module.run_dependency_probes(
        correlation_id="corr-db-no-auth",
        specs=(_giraffe_db_spec(module),),
        transport=httpx.MockTransport(handler),
    )[0]
    assert calls == 0
    assert result.status == "misconfigured"
    assert result.error_code == "DEPENDENCY_PROBE_MISCONFIGURED"


def test_giraffe_db_probe_without_trusted_tenant_makes_zero_requests(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://giraffe-db.test")
    monkeypatch.setenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "gpm.persistence.v1")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "service-secret")
    monkeypatch.delenv("AIVAN_DEPENDENCY_PROBE_TENANT_ID", raising=False)
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "ready", "version": "v1"})

    result = module.run_dependency_probes(
        correlation_id="corr-db-no-tenant",
        specs=(_giraffe_db_spec(module),),
        transport=httpx.MockTransport(handler),
    )[0]
    assert calls == 0
    assert result.status == "misconfigured"


@pytest.mark.parametrize(
    ("status", "expected_ready"),
    [("down", False), ("ready", True)],
)
def test_shared_health_and_version_endpoint_always_enforces_health(
    monkeypatch, status, expected_ready
):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("SHARED_BASE_URL", "http://shared.test")
    monkeypatch.setenv("SHARED_EXPECTED_VERSION", "v1")
    spec = module.DependencyProbeSpec(
        dependency_id="shared",
        owner="Shared",
        endpoint_class="shared-health-version",
        base_url_env="SHARED_BASE_URL",
        expected_version_env="SHARED_EXPECTED_VERSION",
        health_path="/healthz",
        version_path="/healthz",
        timeout_seconds=0.5,
        stale_after_seconds=30.0,
        criticality="critical",
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"status": status, "version": "v1"})
    )
    result = module.run_dependency_probes(
        correlation_id="corr-shared",
        specs=(spec,),
        transport=transport,
    )[0]
    assert result.ready is expected_ready
    assert result.error_code == (None if expected_ready else "DEPENDENCY_NOT_READY")


def test_openapi_mutation_policy_is_total_unique_and_machine_readable():
    module = importlib.import_module("aivan.observability.dependency_probe")
    app = importlib.import_module("aivan.api.main").app
    mutation_methods = {"post", "put", "patch", "delete"}
    openapi_mutations = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in mutation_methods
    }
    entries = module.mutation_policy_entries()
    keys = [(entry.method, entry.path_template) for entry in entries]

    assert len(keys) == len(set(keys))
    assert set(keys) == openapi_mutations
    assert all(entry.policy_version == "aivan.mutation-policy.v1" for entry in entries)
    assert all(entry.classification in {"guarded", "not_applicable"} for entry in entries)
    assert all(entry.reason for entry in entries)
    for path in (
        "/api/platforms/suggestions/{suggestion_id}/approve",
        "/api/platforms/suggestions/{suggestion_id}/reject",
        "/api/platforms/suggestions/{suggestion_id}/block",
        "/api/platforms/whitelist",
        "/api/openclaw/accounts/register",
        "/api/openclaw/accounts/{account_connection_id}/revoke",
        "/api/events/{event_id}/reverse",
        "/api/suppliers/import",
    ):
        entry = next(item for item in entries if item.path_template == path)
        assert entry.classification == "guarded"


@pytest.fixture
def actual_app_with_failed_dependencies(
    monkeypatch, production_runtime_policy
) -> Iterator[tuple[TestClient, object]]:
    module = importlib.import_module("aivan.observability.dependency_probe")
    main = importlib.import_module("aivan.api.main")
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "stage-b1a-key")
    monkeypatch.setenv("AIVAN_TENANT_ID", "stage-b1a-tenant")
    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", "c" * 40)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "_load_supplier_registry_on_startup", lambda: 0)

    def failed(*, correlation_id: str):
        return [
            module.DependencyProbeResult(
                dependency_id="giraffe-db",
                contract_version="aivan.dependency-probe.v1",
                criticality="critical",
                owner="DB",
                expected_version="gpm.persistence.v1",
                observed_version=None,
                status="unavailable",
                error_code="DEPENDENCY_UNAVAILABLE",
                correlation_id=correlation_id,
                checked_at_epoch=1.0,
                duration_seconds=0.001,
                stale_after_seconds=30.0,
            )
        ]

    monkeypatch.setattr(module, "run_dependency_probes", failed)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, module


def _materialize(path_template: str) -> str:
    values = {
        "{draft_id}": "d1",
        "{event_id}": "e1",
        "{account_connection_id}": "a1",
        "{suggestion_id}": "s1",
        "{project_id}": "p1",
    }
    path = path_template
    for marker, value in values.items():
        path = path.replace(marker, value)
    return path


def test_actual_app_blocks_every_guarded_mutation_before_handler_side_effects(
    actual_app_with_failed_dependencies,
):
    client, module = actual_app_with_failed_dependencies
    headers = {
        "X-AIVAN-API-Key": "stage-b1a-key",
        "X-AIVAN-Tenant-ID": "stage-b1a-tenant",
        "X-AIVAN-Trace-ID": "corr-all-mutations",
    }
    guarded = [
        entry
        for entry in module.mutation_policy_entries()
        if entry.classification == "guarded"
    ]
    assert guarded
    for entry in guarded:
        response = client.request(
            entry.method,
            _materialize(entry.path_template),
            headers=headers,
            json={},
        )
        assert response.status_code == 503, (entry.method, entry.path_template, response.text)
        assert response.json() == {
            "error": "critical_dependency_unavailable",
            "correlation_id": "corr-all-mutations",
        }


def test_required_probe_orchestration_has_bounded_parallel_amplification():
    module = importlib.import_module("aivan.observability.dependency_probe")
    specs = module.required_dependency_specs()
    assert len(specs) <= module.MAX_REQUIRED_DEPENDENCIES == 4
    assert module.MAX_HTTP_REQUESTS_PER_DEPENDENCY == 2
    assert module.MAX_CONCURRENT_PROBE_TASKS == 4
    assert len(specs) * module.MAX_HTTP_REQUESTS_PER_DEPENDENCY <= 8
    assert all(spec.timeout_seconds <= module.probe_total_timeout_seconds() for spec in specs)


def test_four_provider_probe_fanout_is_parallel_and_one_request_for_shared_endpoints(
    monkeypatch,
):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    barrier = threading.Barrier(4, timeout=2.0)
    calls: list[str] = []
    specs = []
    for index in range(4):
        monkeypatch.setenv(f"PROBE_{index}_BASE_URL", f"http://provider-{index}.test")
        monkeypatch.setenv(f"PROBE_{index}_VERSION", "v1")
        specs.append(
            module.DependencyProbeSpec(
                dependency_id=f"provider-{index}",
                owner=f"owner-{index}",
                endpoint_class="shared-health-version",
                base_url_env=f"PROBE_{index}_BASE_URL",
                expected_version_env=f"PROBE_{index}_VERSION",
                health_path="/healthz",
                version_path="/healthz",
                timeout_seconds=1.0,
                stale_after_seconds=30.0,
                criticality="critical",
            )
        )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        barrier.wait()
        return httpx.Response(200, json={"status": "ready", "version": "v1"})

    results = module.run_dependency_probes(
        correlation_id="corr-parallel",
        specs=tuple(specs),
        transport=httpx.MockTransport(handler),
    )
    assert all(result.ready for result in results)
    assert sorted(calls) == [f"provider-{index}.test" for index in range(4)]


def test_probe_batch_returns_within_total_budget_when_a_transport_stalls(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_DEPENDENCY_PROBE_TOTAL_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("STALL_BASE_URL", "http://stall.test")
    monkeypatch.setenv("STALL_VERSION", "v1")
    spec = module.DependencyProbeSpec(
        dependency_id="stall",
        owner="stall-owner",
        endpoint_class="shared-health-version",
        base_url_env="STALL_BASE_URL",
        expected_version_env="STALL_VERSION",
        health_path="/healthz",
        version_path="/healthz",
        timeout_seconds=1.0,
        stale_after_seconds=30.0,
        criticality="critical",
    )
    completed = threading.Event()

    def handler(_request: httpx.Request) -> httpx.Response:
        time.sleep(0.25)
        completed.set()
        return httpx.Response(200, json={"status": "ready", "version": "v1"})

    started = time.perf_counter()
    result = module.run_dependency_probes(
        correlation_id="corr-stall",
        specs=(spec,),
        transport=httpx.MockTransport(handler),
    )[0]
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2
    assert result.status == "timeout"
    assert result.error_code == "DEPENDENCY_TIMEOUT"
    assert completed.wait(timeout=1.0)


def test_process_wide_probe_slot_saturation_fails_closed_without_queueing(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    entered = threading.Barrier(5, timeout=2.0)
    release = threading.Event()
    first_results: list[object] = []
    specs = []
    for index in range(4):
        monkeypatch.setenv(f"SAT_{index}_BASE_URL", f"http://sat-{index}.test")
        monkeypatch.setenv(f"SAT_{index}_VERSION", "v1")
        specs.append(
            module.DependencyProbeSpec(
                dependency_id=f"sat-{index}",
                owner=f"owner-{index}",
                endpoint_class="shared-health-version",
                base_url_env=f"SAT_{index}_BASE_URL",
                expected_version_env=f"SAT_{index}_VERSION",
                health_path="/healthz",
                version_path="/healthz",
                timeout_seconds=1.0,
                stale_after_seconds=30.0,
                criticality="critical",
            )
        )

    def handler(_request: httpx.Request) -> httpx.Response:
        entered.wait()
        assert release.wait(timeout=2.0)
        return httpx.Response(200, json={"status": "ready", "version": "v1"})

    def run_first_batch() -> None:
        first_results.extend(
            module.run_dependency_probes(
                correlation_id="corr-saturated-first",
                specs=tuple(specs),
                transport=httpx.MockTransport(handler),
            )
        )

    thread = threading.Thread(target=run_first_batch)
    thread.start()
    entered.wait()
    started = time.perf_counter()
    saturated = module.run_dependency_probes(
        correlation_id="corr-saturated-second",
        specs=(specs[0],),
        transport=httpx.MockTransport(handler),
    )[0]
    elapsed = time.perf_counter() - started
    release.set()
    thread.join(timeout=3.0)

    assert elapsed < 0.2
    assert saturated.status == "timeout"
    assert saturated.error_code == "DEPENDENCY_TIMEOUT"
    assert len(first_results) == 4
    assert all(result.ready for result in first_results)
