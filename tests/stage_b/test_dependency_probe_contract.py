from __future__ import annotations

import importlib
import json

import httpx


def _production_contract(monkeypatch) -> None:
    values = {
        "AIVAN_ENV": "production",
        "AIVAN_CANDIDATE_SHA": "b" * 40,
        "AIVAN_DB_URL": "sqlite:///./data/aivan.db",
        "AIVAN_TENANT_ID": "tenant-1",
        "AIVAN_API_KEY": "injected",
        "AIVAN_UI_SESSION_SECRET": "s" * 40,
        "AIVAN_UI_ACTOR_ID": "operator-1",
        "AIVAN_UI_ALLOWED_ROLES": "sales,approver",
        "AIVAN_CORS_ORIGINS": "https://myaivan.com",
        "AIVAN_PORT": "8765",
        "GIRAFFE_DB_BASE_URL": "http://127.0.0.1:9000",
        "GLTG_API_BASE_URL": "http://127.0.0.1:8090",
        "OPENCLAW_BASE_URL": "http://127.0.0.1:3000",
        "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3.5:9b",
        "AIVAN_NON_CHINA_EGRESS_POLICY": "abcdyi-sin",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "AIVAN_LANGUAGE_SKILL_BASE_URL": "http://127.0.0.1:8788",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER": "ctranslate2",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL": "opus-mt",
        "AIVAN_TRANSLATION_PROOFREAD_ENABLED": "true",
        "AIVAN_PRODUCT_ROLE": "monitoring_takeover_control_plane",
        "AIVAN_BUSINESS_FACT_AUTHORITY": "giraffe-db",
        "AIVAN_LOCAL_STATE_SCOPE": "control_audit_cache_only",
        "AIVAN_ALLOW_STUB_SUPPLIERS": "false",
        "AIVAN_WEB_SEARCH_PROVIDER": "openclaw_search",
        "AIVAN_ALIBABA_MODE": "official_api",
        "GPM_LLM_RUNTIME_MODE": "live",
        "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_readyz_calls_real_probes_and_rejects_config_only_green(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    readiness = importlib.import_module("aivan.observability.readiness")
    _production_contract(monkeypatch)
    called: list[str] = []

    def failing_probe(*, correlation_id: str):
        called.append(correlation_id)
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

    monkeypatch.setattr(readiness, "run_dependency_probes", failing_probe)
    checks = readiness.readiness_checks(correlation_id="corr-readyz")
    assert called == ["corr-readyz"]
    assert checks["critical_dependencies_ready"] is False
    assert not all(checks.values())


def test_required_dependency_version_mismatch_is_not_ready(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    spec = module.DependencyProbeSpec(
        dependency_id="example",
        owner="Example owner",
        endpoint_class="service-health-and-version",
        base_url_env="EXAMPLE_BASE_URL",
        expected_version_env="EXAMPLE_EXPECTED_VERSION",
        health_path="/healthz",
        version_path="/version",
        timeout_seconds=0.5,
        stale_after_seconds=30.0,
        criticality="critical",
    )
    monkeypatch.setenv("EXAMPLE_BASE_URL", "http://example.test")
    monkeypatch.setenv("EXAMPLE_EXPECTED_VERSION", "v1")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"status": "ok"} if request.url.path == "/healthz" else {"version": "v2"}
        return httpx.Response(200, json=payload)

    results = module.run_dependency_probes(
        correlation_id="corr-version",
        specs=(spec,),
        transport=httpx.MockTransport(handler),
    )
    assert len(results) == 1
    assert results[0].status == "incompatible"
    assert results[0].error_code == "DEPENDENCY_VERSION_MISMATCH"
    assert results[0].ready is False


def test_probe_timeout_returns_stable_code_and_correlation_without_provider_details(monkeypatch):
    module = importlib.import_module("aivan.observability.dependency_probe")
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("EXAMPLE_BASE_URL", "http://secret-host.invalid/sensitive")
    monkeypatch.setenv("EXAMPLE_EXPECTED_VERSION", "v1")
    spec = module.DependencyProbeSpec(
        dependency_id="example",
        owner="Example owner",
        endpoint_class="service-health-and-version",
        base_url_env="EXAMPLE_BASE_URL",
        expected_version_env="EXAMPLE_EXPECTED_VERSION",
        health_path="/healthz",
        version_path="/version",
        timeout_seconds=0.01,
        stale_after_seconds=30.0,
        criticality="critical",
    )

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider-secret-detail", request=request)

    result = module.run_dependency_probes(
        correlation_id="corr-timeout",
        specs=(spec,),
        transport=httpx.MockTransport(timeout),
    )[0]
    encoded = json.dumps(result.to_public_dict(), sort_keys=True)
    assert result.error_code == "DEPENDENCY_TIMEOUT"
    assert result.correlation_id == "corr-timeout"
    assert "provider-secret-detail" not in encoded
    assert "secret-host" not in encoded
    assert "sensitive" not in encoded


def test_all_required_dependencies_declare_probe_version_slo_and_owner():
    module = importlib.import_module("aivan.observability.dependency_probe")
    specs = module.required_dependency_specs()
    assert {spec.dependency_id for spec in specs} == {
        "giraffe-db",
        "gltg",
        "openclaw",
        "giraffe-language-skill",
    }
    for spec in specs:
        assert spec.contract_version == "aivan.dependency-probe-spec.v1"
        assert spec.owner
        assert spec.endpoint_class
        assert spec.expected_version_env
        assert spec.version_path
        assert spec.timeout_seconds > 0
        assert spec.stale_after_seconds >= spec.timeout_seconds
        assert spec.criticality in {"critical", "optional"}
