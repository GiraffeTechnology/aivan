"""Deployment profiles eliminate source edits while preserving fail-closed setup."""
import importlib.util
import json
from pathlib import Path
import socket

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location("installer_review_" + name, ROOT / "installer" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module("runtime")
deployment = module("deployment_config")
healthcheck = module("healthcheck")


def write_private(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


def config():
    value = runtime.new_config(["tenant-a", "tenant-b"])
    value["database_mode"] = "isolated"
    return value


def test_occupied_port_falls_back_without_disrupting_owner():
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen()
        port = existing.getsockname()[1]
        listener, selected = runtime.bind_available_port(port, set(), set())
        try:
            assert selected != port
            assert existing.getsockname()[1] == port
        finally:
            listener.close()


@pytest.mark.parametrize("ports", [[-1], [True], [65536], ["443"], "443"])
def test_invalid_reserved_port_configuration_rejected(ports):
    value = config()
    value["reserved_ports"] = ports
    with pytest.raises(ValueError):
        runtime.validate_config(value)


def test_private_file_rejects_public_permissions_and_symlink(tmp_path):
    path = write_private(tmp_path / "credentials.json", {})
    path.chmod(0o644)
    with pytest.raises(ValueError):
        deployment.private_json(path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        deployment.private_json(link)


def test_profile_preserves_installation_identity_and_merges_only_values():
    before = config()
    result = deployment.profile(before, {
        "version": 1, "origin": "https://myaivan.example", "reserved_ports": [14443],
        "requested_ports": {"web": 0}, "external": {"gpm": "https://gpm.example"},
    }, endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants)
    assert result["secrets"] == before["secrets"]
    assert result["tenants"] == before["tenants"]
    assert result["ports"]["web"] == 0
    assert result["external"]["gpm"] == "https://gpm.example"
    assert before["external"] == {}


@pytest.mark.parametrize("extra", [{"secrets": {}}, {"tenant_ids": ["replacement"]}, {"external": {"database": "https://db.example"}}])
def test_profile_rejects_silent_identity_changes(extra):
    with pytest.raises(ValueError):
        deployment.profile(config(), {"version": 1, **extra}, endpoint=runtime.endpoint, tenant_identities=runtime.fulfillment_tenants)


def test_credentials_cover_exact_tenants_and_never_overwrite_frontend_keys(tmp_path):
    value = config()
    value["external"] = {"gpm": "https://gpm.example", "database": "https://db.example", "gltg": "https://gltg.example"}
    secrets = {"database": {"tenant_service_auth": {"tenant-a": "provider-a", "tenant-b": "provider-b"}},
               "gpm": {"tenant_keys": {"tenant-a": "pricing-a", "tenant-b": "pricing-b"}},
               "gltg": {"service_auth": "leadtime-credential"}}
    value["service_credentials_file"] = str(write_private(tmp_path / "credentials.json", {"version": 1, "services": secrets}))
    result = deployment.credential_environment(value)
    assert json.loads(result["GPM_TENANT_API_KEYS"]) == secrets["gpm"]["tenant_keys"]
    assert json.loads(result["GLTG_GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON"]) == secrets["database"]["tenant_service_auth"]
    assert "AIVAN_TENANT_API_KEYS" not in result
    assert "GLTG_INBOUND_SERVICE_AUTH_SECRET" not in result
    secrets["gpm"]["tenant_keys"].pop("tenant-b")
    write_private(tmp_path / "credentials.json", {"version": 1, "services": secrets})
    with pytest.raises(ValueError, match="exactly"):
        deployment.credentials(value)


def test_email_requires_explicit_enablement_and_preserves_human_approval(tmp_path):
    value = config()
    value["channels"]["openclaw_url"] = "https://gateway.example"
    value["service_credentials_file"] = str(write_private(tmp_path / "credentials.json", {"version": 1, "services": {"openclaw": {"api_key": "existing-gateway-key"}}}))
    (tmp_path / "manifest.json").write_text(json.dumps({"components": {"aivan": {"revision": "a" * 40}}}))
    assert runtime.environment(tmp_path, tmp_path, value)["OPENCLAW_BASE_URL"] == ""
    value["channels"]["email_enabled"] = True
    env = runtime.environment(tmp_path, tmp_path, value)
    assert env["OPENCLAW_BASE_URL"] == "https://gateway.example"
    assert env["OPENCLAW_API_KEY"] == "existing-gateway-key"
    assert env["OPENCLAW_MOCK_MODE"] == "false"
    assert env["AIVAN_REQUIRE_HUMAN_APPROVAL"] == "true"


@pytest.mark.parametrize("path", ["//foreign.example/send", "/send?token=secret", "/send#fragment", "/send\nInjected", "/send\\other"])
def test_unsafe_gateway_paths_rejected(path):
    value = config()
    value["channels"]["send_endpoint"] = path
    with pytest.raises(ValueError):
        runtime.validate_config(value)


def test_ports_file_contains_actual_values_and_no_credentials(tmp_path):
    value = config()
    runtime.publish_ports(tmp_path, value)
    result = json.loads((tmp_path / "run/ports.json").read_text())
    assert result["services"]["web"]["port"] == value["ports"]["web"]
    assert not any(secret in json.dumps(result) for secret in value["tenants"].values())
    assert not any(secret in json.dumps(result) for secret in value["secrets"].values())


def test_http_200_not_ready_is_never_a_green_health_result(monkeypatch):
    value = config()
    def respond(url, headers=None):
        if url.endswith("/readiness"):
            return {"status": "ok", "tenant_id": headers["X-AIVAN-Tenant-ID"], "packet_persistence": "durable"}
        return {"status": "not_ready", "packet_persistence": "in_memory_only"}
    monkeypatch.setattr(healthcheck, "request_json", respond)
    assert healthcheck.probe(value, {"gpm": runtime.SERVICES["gpm"]}, {})["gpm"]["ok"] is False


def test_every_gpm_tenant_is_probed_and_cross_tenant_response_rejected(monkeypatch):
    value = config()
    seen = []
    def respond(url, headers=None):
        if url.endswith("/readiness"):
            seen.append(headers["X-AIVAN-Tenant-ID"])
            return {"status": "ok", "tenant_id": "tenant-a", "packet_persistence": "durable"}
        return {"status": "ok", "packet_persistence": "durable"}
    monkeypatch.setattr(healthcheck, "request_json", respond)
    result = healthcheck.probe(value, {"gpm": runtime.SERVICES["gpm"]}, {})
    assert seen == ["tenant-a", "tenant-b"]
    assert result["gpm"]["ok"] is False
    assert result["gpm"]["tenants"] == {"tenant-a": True, "tenant-b": False}


@pytest.mark.parametrize("host_profile", ["isolated", "ctyun", "sin", "other"])
@pytest.mark.parametrize("origin", ["https://myaivan.example", "https://myaivan.example:443"])
def test_host_profiles_do_not_invent_port_reservations(monkeypatch, host_profile, origin):
    monkeypatch.delenv("AIVAN_RESERVED_PORTS", raising=False)
    value = config()
    value["host_profile"] = host_profile
    value["database_mode"] = "external"
    value["origin"] = origin
    value["ports"]["web"] = 8443
    runtime.validate_config(value)
    assert deployment.reserved_ports(value) == set()
    assert value["origin"] == origin


@pytest.mark.parametrize("host_profile", ["isolated", "ctyun", "sin", "other"])
@pytest.mark.parametrize("port", [443, 1023, -1, 65536, True])
def test_internal_listeners_keep_unprivileged_port_boundary(monkeypatch, host_profile, port):
    monkeypatch.delenv("AIVAN_RESERVED_PORTS", raising=False)
    value = config()
    value["host_profile"] = host_profile
    value["database_mode"] = "external"
    value["ports"]["web"] = port
    with pytest.raises(ValueError, match="unprivileged"):
        runtime.validate_config(value)


@pytest.mark.parametrize("host_profile", ["isolated", "ctyun", "sin", "other"])
def test_readiness_receives_exact_configured_reservations(tmp_path, monkeypatch, host_profile):
    monkeypatch.setenv("AIVAN_RESERVED_PORTS", "8443,443")
    value = config()
    value["host_profile"] = host_profile
    value["reserved_ports"] = [443, 14555]
    monkeypatch.setattr(runtime, "load_database_module", lambda: type("Database", (), {
        "configured_targets": staticmethod(lambda config, root: {
            "aivan": {"url": "sqlite:///synthetic", "schema": ""},
            "abcdyi": {"url": "sqlite:///synthetic-abcdyi", "schema": ""},
            "database": {"url": "sqlite:///synthetic-provider", "schema": ""},
        })
    }))
    (tmp_path / "manifest.json").write_text(json.dumps({"components": {"aivan": {"revision": "a" * 40}}}))
    env = runtime.environment(tmp_path, tmp_path, value)
    assert env["AIVAN_RESERVED_PORTS"] == "443,8443,14555"
    assert env["AIVAN_PORT"] == str(value["ports"]["web"])
    assert env["AIVAN_REQUIRE_HUMAN_APPROVAL"] == "true"


def test_reserved_port_allocation_skips_only_explicit_values(monkeypatch):
    monkeypatch.delenv("AIVAN_RESERVED_PORTS", raising=False)
    requested = runtime.reserve_port()
    listener, selected = runtime.bind_available_port(requested, {443, requested}, set())
    try:
        assert selected not in {443, requested}
        assert listener.getsockname() == ("127.0.0.1", selected)
    finally:
        listener.close()
