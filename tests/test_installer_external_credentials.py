"""External services never inherit installation-owned authentication secrets."""
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        "external_credentials_test_" + name, ROOT / "installer" / (name + ".py")
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module("runtime")
deployment = module("deployment_config")
healthcheck = module("healthcheck")


def config(*external):
    value = runtime.new_config(["tenant-a", "tenant-b"])
    value["database_mode"] = "isolated"
    value["external"] = {name: f"https://{name}.example.invalid" for name in external}
    return value


def write_credentials(tmp_path, value, services):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"version": 1, "services": services}))
    path.chmod(0o600)
    value["service_credentials_file"] = str(path)


def manifest(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"components": {"aivan": {"revision": "a" * 40}}})
    )


@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
def test_external_environment_rejects_missing_credentials(service):
    value = config(service)
    with pytest.raises(ValueError, match="credentials") as error:
        deployment.credential_environment(value)
    assert service in str(error.value)
    assert "service_credentials_file" in str(error.value)
    assert not any(secret in str(error.value) for secret in value["secrets"].values())
    assert not any(secret in str(error.value) for secret in value["tenants"].values())


@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
def test_runtime_environment_rejects_missing_external_credentials(tmp_path, service):
    value = config(service)
    manifest(tmp_path)
    with pytest.raises(ValueError, match="credentials"):
        runtime.environment(tmp_path, tmp_path, value)


def test_partial_external_credentials_never_enable_local_fallback(tmp_path):
    value = config("database", "gltg", "gpm")
    write_credentials(tmp_path, value, {"gltg": {"service_auth": "synthetic-provider-gltg"}})
    with pytest.raises(ValueError, match="credentials") as error:
        deployment.credential_environment(value)
    assert "database" in str(error.value)
    assert "gpm" in str(error.value)
    assert "synthetic-provider-gltg" not in str(error.value)


@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
@pytest.mark.parametrize("url", ["https://provider.example.invalid", "http://127.0.0.1:19000"])
def test_missing_external_credentials_block_every_service_request(monkeypatch, service, url):
    value = config(service)
    value["external"][service] = url
    requests = []

    def respond(url, headers=None):
        requests.append((url, headers))
        return {"status": "ok", "packet_persistence": "durable", "ready": True,
                "giraffe_db": "ok", "persistence_enabled": True,
                "tenant_id": (headers or {}).get("X-AIVAN-Tenant-ID")}

    monkeypatch.setattr(healthcheck, "request_json", respond)
    report = healthcheck.probe(value, {service: runtime.SERVICES[service]}, {})
    assert requests == []
    assert report[service]["ok"] is False
    assert report[service]["status"] == "credentials_required"
    assert "service_credentials_file" in report[service]["message"]
    assert not any(secret in json.dumps(report) for secret in value["secrets"].values())
    assert not any(secret in json.dumps(report) for secret in value["tenants"].values())


def test_prepared_external_endpoints_can_wait_for_credentials():
    value = config("database", "gltg", "gpm")
    runtime.validate_config(value)
    assert deployment.credentials(value) == {}


def test_staged_partial_credentials_require_completeness_only_at_startup(tmp_path):
    value = config("database", "gltg", "gpm")
    supplied = {"gltg": {"service_auth": "synthetic-provider-gltg"}}
    write_credentials(tmp_path, value, supplied)
    assert deployment.credentials(value) == supplied
    with pytest.raises(ValueError, match="credentials"):
        deployment.credentials(value, require_external=True)


@pytest.mark.parametrize("keys", [
    {}, {"tenant-a": "synthetic-a"},
    {"tenant-a": "synthetic-a", "tenant-b": "synthetic-b", "tenant-other": "synthetic-other"},
    {"tenant-a": "synthetic-a", "tenant-b": ""},
    {"tenant-a": "synthetic-a", "tenant-b": "synthetic-b\nInjected: bad"},
    {"tenant-a": "synthetic-a", "tenant-b": None},
    [], None,
])
def test_incomplete_or_unsafe_external_gpm_keys_never_send_any_request(monkeypatch, keys):
    value = config("gpm")
    monkeypatch.setattr(healthcheck, "request_json", lambda *args, **kwargs: pytest.fail("Unexpected request"))
    report = healthcheck.probe(value, {"gpm": runtime.SERVICES["gpm"]}, {"gpm": {"tenant_keys": keys}})
    assert report["gpm"]["ok"] is False
    assert report["gpm"]["status"] == "credentials_required"
    assert "exactly" in report["gpm"]["message"]
    assert "synthetic" not in json.dumps(report)


@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
@pytest.mark.parametrize("descriptor", [None, {}, "synthetic-invalid-descriptor", []])
def test_missing_credential_descriptors_never_send_any_request(monkeypatch, service, descriptor):
    value = config(service)
    monkeypatch.setattr(healthcheck, "request_json", lambda *args, **kwargs: pytest.fail("Unexpected request"))
    report = healthcheck.probe(value, {service: runtime.SERVICES[service]}, {service: descriptor})
    assert report[service]["ok"] is False
    assert report[service]["status"] == "credentials_required"


@pytest.mark.parametrize("service, descriptor", [
    ("database", {"tenant_service_auth": {"tenant-a": "synthetic-db-a"}}),
    ("gpm", {"tenant_keys": {"tenant-a": "synthetic-gpm-a"}}),
    ("gltg", {"service_auth": "synthetic\ninvalid"}),
])
def test_staging_still_rejects_invalid_supplied_credentials(tmp_path, service, descriptor):
    value = config(service)
    write_credentials(tmp_path, value, {service: descriptor})
    with pytest.raises(ValueError):
        deployment.credentials(value)


@pytest.mark.parametrize("service, descriptor", [
    ("database", {"service_auth": "synthetic-db"}),
    ("gltg", {"service_auth": "synthetic-gltg"}),
    ("gpm", {"tenant_keys": {"tenant-a": "synthetic-gpm-a", "tenant-b": "synthetic-gpm-b"}}),
])
def test_external_credentials_cannot_be_assigned_to_a_managed_service(tmp_path, service, descriptor):
    value = config()
    write_credentials(tmp_path, value, {service: descriptor})
    with pytest.raises(ValueError, match="corresponding external service"):
        deployment.credentials(value, require_external=True)


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("service", ["database", "gltg", "gpm"])
def test_start_validates_external_credentials_before_service_changes(tmp_path, monkeypatch, service, running):
    runtime.write_json(tmp_path / "config.json", config(service))
    runtime.write_json(tmp_path / "systemd.json", {})
    monkeypatch.setattr(runtime, "status", lambda _root: {"running": running})
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped services before validation"))
    monkeypatch.setattr(runtime, "wait_healthy", lambda _root: pytest.fail("Probed services before validation"))
    monkeypatch.setattr(runtime, "load_service_module", lambda: pytest.fail("Started services before validation"))
    with pytest.raises(ValueError, match="credentials"):
        runtime.start(tmp_path)


def staged_installation(tmp_path):
    root = tmp_path / "installation"
    runtime.check_root(root, initialize=True)
    payload = tmp_path / "payload"
    payload.mkdir()
    runtime.write_json(payload / "manifest.json", {
        "release": "synthetic-no-start",
        "components": {"aivan": {"revision": "a" * 40}}, "files": {},
    })
    profile = tmp_path / "profile.json"
    runtime.write_json(profile, {
        "version": 1, "private_data_provider_id": "synthetic-external-provider",
        "external": config("database", "gltg", "gpm")["external"],
    })
    return root, payload, profile


def test_no_start_install_accepts_endpoints_before_credentials(tmp_path, monkeypatch):
    root, payload, profile = staged_installation(tmp_path)
    monkeypatch.setattr(runtime, "start", lambda _root: pytest.fail("Unexpected startup"))
    result = runtime.install(root, payload, ["tenant-a", "tenant-b"], 0, True, profile_file=profile)
    stored = runtime.read_json(root / "config.json")
    assert result["started"] is False
    assert set(stored["external"]) == {"database", "gltg", "gpm"}
    assert stored["service_credentials_file"] == ""
    assert deployment.credentials(stored) == {}
    with pytest.raises(ValueError, match="credentials"):
        deployment.credential_environment(stored)


def test_install_with_start_rejects_missing_credentials_before_stopping(tmp_path, monkeypatch):
    root, payload, profile = staged_installation(tmp_path)
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped before validation"))
    with pytest.raises(ValueError, match="credentials"):
        runtime.install(root, payload, ["tenant-a", "tenant-b"], 0, False, profile_file=profile)
    assert not (root / "current").exists()


def test_prepare_accepts_endpoints_without_starting_then_restart_fails_safely(tmp_path, monkeypatch, capsys):
    root, payload, _profile = staged_installation(tmp_path)
    runtime.install(root, payload, ["tenant-a", "tenant-b"], 0, True)
    monkeypatch.setattr(runtime, "start", lambda _root: pytest.fail("Unexpected startup"))
    runtime.main(["--prefix", str(root), "prepare",
                  "--database-url", "https://database.example.invalid",
                  "--database-provider-id", "synthetic-external-provider",
                  "--gltg-url", "https://gltg.example.invalid",
                  "--gpm-url", "https://gpm.example.invalid"])
    stored = runtime.read_json(root / "config.json")
    assert set(stored["external"]) == {"database", "gltg", "gpm"}
    assert stored["service_credentials_file"] == ""
    before = (root / "config.json").read_bytes()
    monkeypatch.setattr(runtime, "stop", lambda _root: pytest.fail("Stopped before validation"))
    with pytest.raises(ValueError, match="credentials"):
        runtime.main(["--prefix", str(root), "prepare", "--restart"])
    assert (root / "config.json").read_bytes() == before
    output = capsys.readouterr().out
    assert not any(secret in output for secret in stored["secrets"].values())
    assert not any(secret in output for secret in stored["tenants"].values())


def test_managed_environment_retains_installation_credentials(tmp_path):
    value = config()
    manifest(tmp_path)
    result = runtime.environment(tmp_path, tmp_path, value)
    assert result["GIRAFFE_DB_SERVICE_AUTH_SECRET"] == value["secrets"]["database"]
    assert result["GLTG_SERVICE_AUTH_SECRET"] == value["secrets"]["gltg"]
    assert json.loads(result["GPM_TENANT_API_KEYS"]) == value["tenants"]
    assert result["AIVAN_REQUIRE_HUMAN_APPROVAL"] == "true"


def test_configured_external_environment_uses_only_explicit_outbound_credentials(tmp_path):
    value = config("database", "gltg", "gpm")
    supplied = {
        "database": {"tenant_service_auth": {"tenant-a": "synthetic-db-a", "tenant-b": "synthetic-db-b"}},
        "gltg": {"service_auth": "synthetic-provider-gltg"},
        "gpm": {"tenant_keys": {"tenant-a": "synthetic-gpm-a", "tenant-b": "synthetic-gpm-b"}},
    }
    write_credentials(tmp_path, value, supplied)
    manifest(tmp_path)
    result = runtime.environment(tmp_path, tmp_path, value)
    assert result["GIRAFFE_DB_SERVICE_AUTH_SECRET"] == ""
    assert result["GLTG_GIRAFFE_DB_SERVICE_AUTH_SECRET"] == ""
    assert json.loads(result["GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON"]) == supplied["database"]["tenant_service_auth"]
    assert json.loads(result["GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON"]) == supplied["database"]["tenant_service_auth"]
    assert result["GLTG_SERVICE_AUTH_SECRET"] == supplied["gltg"]["service_auth"]
    assert json.loads(result["GPM_TENANT_API_KEYS"]) == supplied["gpm"]["tenant_keys"]
    assert json.loads(result["AIVAN_TENANT_API_KEYS"]) == value["tenants"]
    assert result["GLTG_INBOUND_SERVICE_AUTH_SECRET"] == value["secrets"]["gltg"]
    assert result["AIVAN_REQUIRE_HUMAN_APPROVAL"] == "true"


@pytest.mark.parametrize("external", [False, True])
def test_health_uses_credentials_from_the_selected_gpm_only(monkeypatch, external):
    value = config(*(["gpm"] if external else []))
    selected = {tenant: "synthetic-external-" + tenant for tenant in value["tenants"]}
    supplied = {"gpm": {"tenant_keys": selected}} if external else {}
    expected = selected if external else value["tenants"]
    seen = {}

    def respond(url, headers=None):
        if headers:
            tenant = headers["X-AIVAN-Tenant-ID"]
            seen[tenant] = headers["X-AIVAN-API-Key"]
            return {"status": "ok", "tenant_id": tenant, "packet_persistence": "durable"}
        return {"status": "ok", "packet_persistence": "durable"}

    monkeypatch.setattr(healthcheck, "request_json", respond)
    report = healthcheck.probe(value, {"gpm": runtime.SERVICES["gpm"]}, supplied)
    assert report["gpm"]["ok"] is True
    assert seen == expected
