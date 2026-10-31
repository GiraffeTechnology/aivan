"""Synthetic composition checks, not target-host or real-service acceptance."""
import json
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_installer_deployment_profile import module, write_private
from aivan.governance.runtime_policy import enforce_runtime_policy, RuntimePolicyError
from aivan.observability import dependency_probe as probes, readiness
from aivan.integrations.giraffe_db_auth import service_auth_for_tenant

runtime = module("runtime")
deployment = module("deployment_config")
VERSIONS = {
    "giraffe-db": "fixture-schema-v1", "gltg": "fixture-leadtime-v1",
    "openclaw": "fixture-gateway-v1", "giraffe-language-skill": "fixture-language-v1",
}


def installed_environment(tmp_path, monkeypatch, *, email=False, research=False,
                          model=False, proofread=False, metadata=True):
    value = runtime.new_config(["tenant-a"])
    value.update(database_mode="isolated", deployment_stage="aivan")
    value["language"]["model"] = "fixture-canonical-validator"
    value["language"]["proofread_enabled"] = proofread
    if metadata:
        value["dependency_versions"] = dict(VERSIONS)
        value["dependency_probe_tenant_id"] = "tenant-a"
        value["egress_policy"] = {"expected": "fixture-bridge", "declared": "fixture-bridge"}
    if email or research:
        value["channels"]["openclaw_url"] = "http://127.0.0.1:19999"
        value["service_credentials_file"] = str(write_private(
            tmp_path / "service-credentials.json",
            {"version": 1, "services": {"openclaw": {"api_key": "fixture-gateway-key"}}},
        ))
    value["channels"]["email_enabled"] = email
    if research:
        value["channels"]["risk_search_enabled"] = True
    if model:
        value["model"] = {"url": "http://127.0.0.1:19998", "name": "qwen3.5:9b"}
    (tmp_path / "manifest.json").write_text(json.dumps({
        "components": {"aivan": {"revision": "a" * 40}},
    }))
    env = runtime.environment(tmp_path, tmp_path, value)
    for key in list(os.environ):
        if key.startswith(("AIVAN_", "MYAIVAN_", "GIRAFFE_", "GLTG_", "GPM_", "OPENCLAW_", "OLLAMA_")):
            monkeypatch.delenv(key)
    for key, item in env.items():
        monkeypatch.setenv(key, item)
    return value, env


def synthetic_http_probes(monkeypatch, broken=""):
    """Replace HTTP only inside this unit fixture; production guard is unchanged."""
    requests = []
    original_client = httpx.Client

    def respond(request):
        requests.append(request)
        spec = next(spec for spec in probes.required_dependency_specs()
                    if os.environ.get(spec.base_url_env)
                    and str(request.url).startswith(os.environ[spec.base_url_env].rstrip("/") + "/"))
        if spec.dependency_id == "giraffe-db":
            assert request.headers["X-Service-Tenant-ID"] == "tenant-a"
            assert request.headers["X-Service-Auth"] == service_auth_for_tenant("tenant-a")
            assert request.headers["X-AIVAN-Correlation-ID"] == request.headers["X-AIVAN-Trace-ID"]
            assert request.headers["X-GPM-Contract-Version"]
        if broken == spec.dependency_id + "-auth":
            return httpx.Response(403, json={"error": "fixture_denied"})
        if broken == spec.dependency_id + "-health":
            return httpx.Response(200, json={"status": "down"})
        version = os.environ[spec.expected_version_env]
        if broken == spec.dependency_id + "-version":
            version = "fixture-incompatible-version"
        return httpx.Response(200, json={
            "status": "ok", "version": version, "schema_version": version,
            "contract_version": version,
        })

    def fixture_client(*args, **kwargs):
        assert kwargs.get("transport") is None
        kwargs["transport"] = httpx.MockTransport(respond)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(probes.httpx, "Client", fixture_client)
    return requests


def selected_app(effects):
    app = FastAPI()
    app.include_router(readiness.router)
    app.middleware("http")(probes.dependency_side_effect_gate)

    @app.post("/invoke")
    def invoke():
        effects.append("business-handler")
        return {"accepted": True}

    return app


def test_manual_copy_zero_model_profile_passes_policy_and_real_probe_orchestration(
    tmp_path, monkeypatch,
):
    value, env = installed_environment(tmp_path, monkeypatch)
    enforce_runtime_policy(component="unit-fixture", environment=env)
    requests = synthetic_http_probes(monkeypatch)
    effects = []
    with TestClient(selected_app(effects)) as client:
        result = client.get("/readyz").json()
        assert result["status"] == "ready"
        assert "openclaw_live_configured" not in result["checks"]
        assert "local_model_configured" not in result["checks"]
        assert "qwen_proofreading_only" not in result["checks"]
        response = client.post("/invoke", headers={
            "X-AIVAN-Tenant-ID": "tenant-a", "X-AIVAN-API-Key": value["tenants"]["tenant-a"],
        })
        assert response.status_code == 200
    assert effects == ["business-handler"]
    assert env["OPENCLAW_BASE_URL"] == ""
    assert env["AIVAN_EMAIL_SEND_MODE"] == "disabled"
    assert env["AIVAN_LLM_API_ENABLED"] == "false"
    assert not any(str(request.url).startswith("http://127.0.0.1:19999") for request in requests)
    assert {spec.dependency_id for spec in probes.required_dependency_specs()
            if spec.criticality == "critical"} == {"giraffe-db", "gltg", "giraffe-language-skill"}
    from aivan.risk.supplier_risk_agent import run_risk_screening
    report = run_risk_screening("Fixture unverified supplier")
    assert report.risk_score.risk_level == "unknown"
    assert report.risk_score.recommended_action == "manual_review_required"


@pytest.mark.parametrize("email,research", [(True, False), (False, True)])
def test_each_selected_gateway_capability_keeps_the_gateway_critical(
    tmp_path, monkeypatch, email, research,
):
    installed_environment(tmp_path, monkeypatch, email=email, research=research)
    synthetic_http_probes(monkeypatch)
    checks = readiness.readiness_checks()
    assert checks["openclaw_live_configured"] is True
    assert all(checks.values())
    spec = next(spec for spec in probes.required_dependency_specs() if spec.dependency_id == "openclaw")
    assert spec.criticality == "critical"


@pytest.mark.parametrize("broken", [
    "giraffe-db-auth", "giraffe-db-health", "gltg-version",
    "giraffe-language-skill-health", "openclaw-auth",
])
def test_selected_dependency_failure_is_not_ready_and_has_zero_handler_effects(
    tmp_path, monkeypatch, broken,
):
    value, _ = installed_environment(tmp_path, monkeypatch, email=broken.startswith("openclaw"))
    synthetic_http_probes(monkeypatch, broken)
    effects = []
    with TestClient(selected_app(effects)) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["checks"]["critical_dependencies_ready"] is False
        response = client.post("/invoke", headers={
            "X-AIVAN-Tenant-ID": "tenant-a", "X-AIVAN-API-Key": value["tenants"]["tenant-a"],
            "X-AIVAN-Trace-ID": "fixture-correlation",
        })
        assert response.status_code == 503
        assert response.json()["correlation_id"] == "fixture-correlation"
    assert effects == []


def test_blank_expected_version_never_calls_that_provider(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch)
    monkeypatch.delenv("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", raising=False)
    requests = synthetic_http_probes(monkeypatch)
    checks = readiness.readiness_checks()
    assert checks["critical_dependencies_ready"] is False
    assert not any(str(request.url).startswith(os.environ["GIRAFFE_DB_BASE_URL"] + "/")
                   for request in requests)


@pytest.mark.parametrize("missing", [
    "AIVAN_EXPECTED_EGRESS_POLICY", "AIVAN_NON_CHINA_EGRESS_POLICY",
])
def test_missing_or_mismatched_egress_declaration_is_never_ready(
    tmp_path, monkeypatch, missing,
):
    installed_environment(tmp_path, monkeypatch)
    monkeypatch.setenv(missing, "fixture-wrong-declaration")
    synthetic_http_probes(monkeypatch)
    assert readiness.readiness_checks()["non_china_policy_declared"] is False
    monkeypatch.delenv(missing)
    assert readiness.readiness_checks()["non_china_policy_declared"] is False


def test_selected_model_and_proofreader_keep_their_checks(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch, model=True, proofread=True)
    synthetic_http_probes(monkeypatch)
    checks = readiness.readiness_checks()
    assert checks["local_model_configured"] is True
    assert checks["qwen_proofreading_only"] is True
    monkeypatch.setenv("OLLAMA_MODEL", "fixture-not-the-approved-proofreader")
    assert readiness.readiness_checks()["qwen_proofreading_only"] is False
    monkeypatch.delenv("OLLAMA_BASE_URL")
    assert readiness.readiness_checks()["local_model_configured"] is False


def test_language_cannot_become_mock_to_make_the_profile_ready(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch)
    synthetic_http_probes(monkeypatch)
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER", "mock")
    checks = readiness.readiness_checks()
    assert checks["translation_provider_not_mock"] is False
    assert checks["language_mock_disabled"] is False


def test_default_profile_does_not_invent_versions_or_egress(tmp_path, monkeypatch):
    _, env = installed_environment(tmp_path, monkeypatch, metadata=False)
    assert env.get("AIVAN_GIRAFFE_DB_EXPECTED_VERSION", "") == ""
    assert env.get("AIVAN_EXPECTED_EGRESS_POLICY", "") == ""
    assert env.get("AIVAN_NON_CHINA_EGRESS_POLICY", "") == ""
    assert readiness.readiness_checks()["critical_dependencies_ready"] is False


def test_existing_source_profiles_keep_strict_legacy_requirements(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch)
    monkeypatch.delenv("MYAIVAN_DEPLOYMENT_STAGE")
    synthetic_http_probes(monkeypatch)
    checks = readiness.readiness_checks()
    assert "openclaw_live_configured" in checks
    assert "local_model_configured" in checks
    assert "qwen_proofreading_only" in checks
    assert checks["openclaw_live_configured"] is False


def test_production_explicit_test_transport_remains_forbidden(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch)
    with pytest.raises(RuntimePolicyError, match="test_transport_disabled"):
        probes.run_dependency_probes(
            correlation_id="fixture", transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )


def test_profile_maps_declared_metadata_without_replacing_identity(tmp_path):
    before = runtime.new_config(["tenant-a"])
    values = {
        "version": 1, "dependency_versions": dict(VERSIONS),
        "dependency_probe_tenant_id": "tenant-a",
        "egress_policy": {"expected": "fixture-bridge", "declared": "fixture-bridge"},
        "language": {"proofread_enabled": False},
        "channels": {"risk_search_enabled": False},
    }
    after = deployment.profile(
        before, values, endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants,
    )
    runtime.validate_config(after)
    assert after["dependency_versions"] == values["dependency_versions"]
    assert after["egress_policy"] == values["egress_policy"]
    assert after["tenants"] == before["tenants"]
    assert after["secrets"] == before["secrets"]


@pytest.mark.parametrize("field,value", [
    ("dependency_versions", {"unrecognized": "v1"}),
    ("dependency_versions", {"gltg": ""}),
    ("dependency_versions", {"gltg": "v1\nInjected"}),
    ("dependency_probe_tenant_id", "other-tenant"),
    ("egress_policy", {"expected": "fixture-only"}),
    ("egress_policy", {"expected": "", "declared": ""}),
    ("egress_policy", {"expected": "fixture", "declared": "fixture\nInjected"}),
])
def test_invalid_supplied_profile_metadata_is_rejected(field, value):
    before = runtime.new_config(["tenant-a"])
    with pytest.raises(ValueError):
        after = deployment.profile(
            before, {"version": 1, field: value},
            endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants,
        )
        runtime.validate_config(after)


def test_probe_uses_the_explicit_tenant_map_without_a_shared_fallback(tmp_path, monkeypatch):
    installed_environment(tmp_path, monkeypatch)
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "")
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", json.dumps({
        "tenant-a": "fixture-only-private-provider-key",
    }))
    requests = synthetic_http_probes(monkeypatch)
    assert all(readiness.readiness_checks().values())
    db_requests = [request for request in requests
                   if str(request.url).startswith(os.environ["GIRAFFE_DB_BASE_URL"] + "/")]
    assert db_requests
    assert all(request.headers["X-Service-Auth"] == "fixture-only-private-provider-key"
               for request in db_requests)


@pytest.mark.parametrize("mapping", [
    '{"other-tenant":"fixture-other"}', 'not-json',
    '{"tenant-a":"fixture-first","tenant-a":"fixture-duplicate"}',
])
def test_bad_tenant_map_never_borrows_the_shared_key_or_sends_db_requests(
    tmp_path, monkeypatch, mapping,
):
    installed_environment(tmp_path, monkeypatch)
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-shared-must-not-be-used")
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON", mapping)
    requests = synthetic_http_probes(monkeypatch)
    assert readiness.readiness_checks()["critical_dependencies_ready"] is False
    assert not any(str(request.url).startswith(os.environ["GIRAFFE_DB_BASE_URL"] + "/")
                   for request in requests)
