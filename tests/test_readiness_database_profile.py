"""Read-only selected-database readiness; no SQL or network acceptance claims."""
from __future__ import annotations

import json
import time

import pytest
from starlette.requests import Request

from aivan.observability import readiness


@pytest.fixture(autouse=True)
def selected_configuration(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("MYAIVAN_DATABASE_MODE", raising=False)
    monkeypatch.setattr(readiness, "ready_locales", lambda _: ())
    # These tests isolate configuration parsing; never contact configured endpoints.
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [])


def database_ready(monkeypatch, url, mode=None):
    monkeypatch.setenv("AIVAN_DB_URL", url)
    if mode is not None:
        monkeypatch.setenv("MYAIVAN_DATABASE_MODE", mode)
    checks = readiness.readiness_checks()
    assert "database_profile_sqlite" not in checks
    return checks["database_profile_configured"]


@pytest.mark.parametrize("mode", [None, "external"])
@pytest.mark.parametrize("url", [
    "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/aivan",
    "mysql+pymysql://synthetic:synthetic@db.example.invalid/customer_schema?charset=utf8mb4",
    "mysql+pymysql:///customer_schema?unix_socket=/operator-selected/mysql.sock",
    "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/aivan",
    "postgresql+psycopg2://synthetic:synthetic@db.example.invalid/customer_schema",
])
def test_configured_sync_sql_provider_is_not_forced_to_sqlite(monkeypatch, mode, url):
    assert database_ready(monkeypatch, url, mode) is True


@pytest.mark.parametrize("mode", [None, "isolated"])
@pytest.mark.parametrize("url", [
    "sqlite:///./data/aivan.db",
    "sqlite+pysqlite:////operator-selected/history.db",
])
def test_explicit_durable_legacy_sqlite_remains_compatible(monkeypatch, mode, url):
    assert database_ready(monkeypatch, url, mode) is True


@pytest.mark.parametrize("url", [
    "", " ", "not-a-database-url", "http://db.example.invalid/aivan",
    "unknown_provider://db.example.invalid/aivan", "mysql+unknown_driver://db.example.invalid/aivan",
    "mysql+pymysql://db.example.invalid", "mysql+pymysql://db.example.invalid/",
    "mysql+pymysql://db.example.invalid:invalid/aivan", "mysql+pymysql://db.example.invalid:0/aivan",
    "mysql+pymysql://db.example.invalid:65536/aivan", "mysql+pymysql://bad host/aivan",
    "mysql+pymysql://db.example.invalid/aivan\nsecret",
    "mysql+aiomysql://synthetic:synthetic@127.0.0.1/aivan",
    "postgresql+asyncpg://synthetic:synthetic@127.0.0.1/aivan",
    "sqlite+aiosqlite:///./data/aivan.db", "sqlite://", "sqlite:///",
    "sqlite:///:memory:", "sqlite:///file::memory:?uri=true",
    "sqlite:///file:shared?mode=memory&cache=shared&uri=true", "sqlite://host/history.db",
    "sqlite://synthetic:synthetic@/history.db",
])
def test_invalid_or_nondurable_configuration_fails_closed(monkeypatch, url):
    assert database_ready(monkeypatch, url) is False


def test_database_parser_rejects_control_characters_before_url_parsing():
    # NUL cannot be placed in a real process environment; test the helper directly.
    assert readiness._database_profile_configured("mysql+pymysql:///aivan\x00") is False


@pytest.mark.parametrize(("mode", "url"), [
    ("external", "sqlite:///./data/aivan.db"),
    ("isolated", "mysql+pymysql://synthetic:synthetic@127.0.0.1/aivan"),
    ("unknown", "mysql+pymysql://synthetic:synthetic@127.0.0.1/aivan"),
])
def test_selected_profile_cannot_silently_change_database_mode(monkeypatch, mode, url):
    assert database_ready(monkeypatch, url, mode) is False


def test_database_configuration_check_never_connects_or_discloses_credentials(monkeypatch):
    import sqlalchemy
    import aivan.db.session as session

    def no_engine(*args, **kwargs):
        pytest.fail("A configuration readiness check must not open a SQL engine")

    monkeypatch.setattr(sqlalchemy, "create_engine", no_engine)
    monkeypatch.setattr(session, "get_engine", no_engine)
    secret = "synthetic-private-marker"
    url = f"mysql+pymysql://synthetic:{secret}@db.example.invalid/aivan"
    assert database_ready(monkeypatch, url, "external") is True
    result = json.loads(readiness.ready(Request({"type": "http", "headers": []})).body)
    assert secret not in json.dumps(result) and url not in json.dumps(result)
    assert result["checks"]["database_profile_configured"] is True


def test_nonproduction_readiness_retains_existing_bounded_contract(monkeypatch):
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("AIVAN_DB_URL", "invalid")
    assert readiness.readiness_checks() == {"environment_non_production": True}


@pytest.mark.parametrize(("mode", "url"), [
    ("", "sqlite:///./data/aivan.db"),
    ("external", "mysql+pymysql://synthetic:synthetic@127.0.0.1:3306/aivan"),
    ("external", "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/aivan"),
])
def test_existing_ready_response_accepts_the_selected_database_profile(monkeypatch, mode, url):
    configured = {
        "AIVAN_DB_URL": url, "MYAIVAN_DATABASE_MODE": mode,
        "AIVAN_CANDIDATE_SHA": "b" * 40, "AIVAN_TENANT_ID": "synthetic-tenant",
        "AIVAN_API_KEY": "synthetic-key", "AIVAN_UI_SESSION_SECRET": "s" * 40,
        "AIVAN_UI_ACTOR_ID": "synthetic-operator", "AIVAN_UI_ALLOWED_ROLES": "sales,approver",
        "AIVAN_CORS_ORIGINS": "https://myaivan.com", "AIVAN_PORT": "9444",
        "AIVAN_RESERVED_PORTS": "443,3306", "GIRAFFE_DB_BASE_URL": "http://127.0.0.1:9000",
        "OPENCLAW_BASE_URL": "http://127.0.0.1:3000", "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_LLM_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3.5:9b", "AIVAN_NON_CHINA_EGRESS_POLICY": "abcdyi-sin",
        "AIVAN_LANGUAGE_SKILL_ENABLED": "true",
        "AIVAN_LANGUAGE_SKILL_BASE_URL": "http://127.0.0.1:8788",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER": "ctranslate2",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL": "opus-mt",
        "AIVAN_TRANSLATION_PROOFREAD_ENABLED": "true",
        "AIVAN_EXPECTED_EGRESS_POLICY": "abcdyi-sin",
        "AIVAN_PRODUCT_ROLE": "monitoring_takeover_control_plane",
        "AIVAN_BUSINESS_FACT_AUTHORITY": "giraffe-db",
        "AIVAN_LOCAL_STATE_SCOPE": "control_audit_cache_only",
        "GPM_LLM_RUNTIME_MODE": "live",
        "AIVAN_WEB_SEARCH_PROVIDER": "live",
        "AIVAN_ALIBABA_MODE": "live",
    }
    for name, value in configured.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(readiness, "ready_locales", lambda _: readiness.GENERATED_LOCALES)
    observed = readiness.DependencyProbeResult(
        dependency_id="synthetic-provider", contract_version="aivan.dependency-probe.v1",
        criticality="critical", owner="synthetic-unit-fixture", expected_version="v1",
        observed_version="v1", status="ready", error_code=None,
        correlation_id="synthetic-config-test", checked_at_epoch=time.time(),
        duration_seconds=0.001, stale_after_seconds=30.0,
    )
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [observed])
    response = readiness.ready(Request({"type": "http", "headers": []}))
    assert response.status_code == 200
    assert all(json.loads(response.body)["checks"].values())
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [])
    response = readiness.ready(Request({"type": "http", "headers": []}))
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["critical_dependencies_ready"] is False
    monkeypatch.setattr(readiness, "run_dependency_probes", lambda **_: [observed])
    monkeypatch.setattr(readiness, "ready_locales", lambda _: ())
    response = readiness.ready(Request({"type": "http", "headers": []}))
    # Product source reconciliation C3 explicitly withdraws the old fixed
    # five-locale gate. Missing unrequested catalogs cannot block a ready
    # English workflow; the critical real language-service probe still must pass.
    assert response.status_code == 200
    assert not any(key.startswith("ui_catalog_") for key in json.loads(response.body)["checks"])
    monkeypatch.setattr(readiness, "ready_locales", lambda _: readiness.GENERATED_LOCALES)
    monkeypatch.setenv("AIVAN_DB_URL", "invalid")
    response = readiness.ready(Request({"type": "http", "headers": []}))
    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["database_profile_configured"] is False



def test_valid_configuration_without_critical_observation_is_not_ready(monkeypatch):
    monkeypatch.setenv("AIVAN_DB_URL", "mysql+pymysql:///synthetic_schema")
    response = readiness.ready(Request({"type": "http", "headers": []}))
    assert response.status_code == 503
    checks = json.loads(response.body)["checks"]
    assert checks["database_profile_configured"] is True
    assert checks["critical_dependencies_ready"] is False


def test_invalid_port_never_exposes_the_database_url_or_credential():
    assert readiness._database_profile_configured(
        "mysql+pymysql://synthetic:private-marker@db.example.invalid:invalid/aivan"
    ) is False

