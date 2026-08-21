from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.api.main import app
from aivan.db.models import Base
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.db.session import get_db
from aivan.openclaw.contracts import OpenClawEvent


@pytest.fixture
def workbench(monkeypatch):
    monkeypatch.setenv("AIVAN_API_KEY", "test-deployment-key")
    monkeypatch.setenv("AIVAN_TENANT_ID", "test_tenant")
    monkeypatch.setenv("AIVAN_UI_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "operator-1")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "admin,buyer,approver,auditor")
    monkeypatch.setenv("AIVAN_UI_DEFAULT_ROLE", "admin")
    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", "a" * 40)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, db
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _login(client: TestClient) -> dict:
    response = client.post(
        "/api/session/login",
        headers={"X-AIVAN-API-Key": "test-deployment-key"},
        json={},
    )
    assert response.status_code == 200
    return response.json()


def _buyer_event(actor_id: str, conversation_id: str) -> OpenClawEvent:
    return OpenClawEvent(
        tenant_id="test_tenant",
        source_trace_id=f"trace-{conversation_id}",
        source="myaivan",
        channel="myaivan",
        conversation_id=conversation_id,
        message_id=f"message-{conversation_id}",
        sender_id=actor_id,
        actor_id=actor_id,
        sender_display_name=actor_id,
        message_text="Need 100 widgets",
        business_role="buyer",
        conversation_role="buyer_thread",
        execution_mode="auto",
        authorization_basis="test",
    )


def _seed_case(db, actor_id: str, conversation_id: str):
    project = ProjectRepository(db).create(
        conversation_id=conversation_id,
        customer_id=actor_id,
        customer_display_name=actor_id,
        channel="myaivan",
        tenant_id="test_tenant",
    )
    event = _buyer_event(actor_id, conversation_id).model_copy(
        update={"project_id": project.project_id}
    )
    CaseDomainRepository(db).bind_inbound_event(project.project_id, event)
    db.commit()
    return project


def test_login_issues_httponly_session_and_csrf_cookie(workbench):
    client, _ = workbench
    payload = _login(client)

    cookie_headers = client.post(
        "/api/session/login",
        headers={"X-AIVAN-API-Key": "test-deployment-key"},
        json={},
    ).headers.get_list("set-cookie")
    session_cookie = next(value for value in cookie_headers if value.startswith("aivan_session="))
    csrf_cookie = next(value for value in cookie_headers if value.startswith("aivan_csrf="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=strict" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert payload["csrf_token"]
    assert payload["allowed_roles"] == ["admin", "buyer", "approver", "auditor"]
    assert client.get("/api/session").json()["authorization_basis"] == "ui_session"


def test_ui_session_rejects_write_without_csrf_and_allows_controlled_role_switch(workbench):
    client, _ = workbench
    payload = _login(client)

    rejected = client.post("/api/session/role", json={"role": "buyer"})
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["error"] == "CSRF_REQUIRED"

    switched = client.post(
        "/api/session/role",
        headers={"X-AIVAN-CSRF": payload["csrf_token"]},
        json={"role": "buyer"},
    )
    assert switched.status_code == 200
    assert switched.json()["role"] == "buyer"

    forbidden = client.post(
        "/api/session/role",
        headers={"X-AIVAN-CSRF": switched.json()["csrf_token"]},
        json={"role": "supplier"},
    )
    assert forbidden.status_code == 403


def test_workbench_paginates_and_projects_cases_by_server_authorized_role(workbench):
    client, db = workbench
    own = _seed_case(db, "operator-1", "own-thread")
    other = _seed_case(db, "buyer-2", "other-thread")
    login = _login(client)

    admin_list = client.get("/api/workbench/cases?limit=1")
    assert admin_list.status_code == 200
    assert admin_list.json()["page"] == {
        "offset": 0,
        "limit": 1,
        "total": 2,
        "has_more": True,
    }

    switched = client.post(
        "/api/session/role",
        headers={"X-AIVAN-CSRF": login["csrf_token"]},
        json={"role": "buyer"},
    ).json()
    buyer_list = client.get("/api/workbench/cases")
    assert buyer_list.status_code == 200
    assert [item["case_id"] for item in buyer_list.json()["items"]] == [own.project_id]
    assert client.get(f"/api/workbench/cases/{other.project_id}").status_code == 404

    detail = client.get(f"/api/workbench/cases/{own.project_id}").json()
    assert detail["audit"] == []
    assert {item["role"] for item in detail["conversations"]} == {"buyer_thread"}
    assert detail["messages"][0]["payload_digest"]
    assert detail["messages"][0]["content_version"] == 1
    assert detail["messages"][0]["content_reference"].startswith("aivan://message-evidence/")
    assert "message_text" not in detail["messages"][0]
    assert client.get(f"/api/workbench/cases/{own.project_id}/export").status_code == 403
    assert switched["role"] == "buyer"


def test_admin_export_includes_frozen_candidate_and_digest_only_messages(workbench):
    client, db = workbench
    project = _seed_case(db, "operator-1", "export-thread")
    _login(client)

    response = client.get(f"/api/workbench/cases/{project.project_id}/export?format=json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_sha"] == "a" * 40
    assert payload["messages"][0]["payload_digest"]
    assert "message_text" not in payload["messages"][0]


def test_myaivan_ui_has_security_headers_and_no_persistent_api_key_storage(workbench):
    client, _ = workbench
    response = client.get("/")
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "onclick=" not in response.text

    root = Path(__file__).resolve().parents[1]
    script = (root / "src/aivan/app/static/app.js").read_text(encoding="utf-8")
    assert "sessionStorage" not in script
    assert "localStorage" not in script
    assert "X-AIVAN-API-Key" in script
    assert "keyInput.value = ''" in script
    assert "state.selectedCase = null" in script


def test_myaivan_ui_has_compact_accessible_persistent_language_entry(workbench):
    client, _ = workbench
    response = client.get("/")
    assert response.status_code == 200
    for code, label, accessible_name in (
        ("en", "EN", "English"),
        ("zh", "简", "简体中文"),
        ("zht", "繁", "繁體中文"),
        ("fr", "FR", "Français"),
        ("es", "ES", "Español"),
        ("de", "DE", "Deutsch"),
        ("ko", "한", "한국어"),
        ("ja", "日", "日本語"),
    ):
        assert f'data-language="{code}"' in response.text
        assert f'aria-label="{accessible_name}"' in response.text
        assert f">{label}</button>" in response.text

    root = Path(__file__).resolve().parents[1]
    i18n = (root / "src/aivan/app/static/i18n.js").read_text(encoding="utf-8")
    assert "myaivan.locale" in i18n
    assert "document.documentElement.lang" in i18n
    assert "canonical_english" not in response.text


def test_readiness_fails_closed_until_production_contract_is_complete(monkeypatch):
    from aivan.observability.readiness import readiness_checks

    monkeypatch.setenv("AIVAN_ENV", "production")
    for name in (
        "AIVAN_CANDIDATE_SHA",
        "AIVAN_DB_URL",
        "AIVAN_TENANT_ID",
        "AIVAN_API_KEY",
        "AIVAN_AUTH_SECRET",
        "AIVAN_UI_SESSION_SECRET",
        "AIVAN_UI_ACTOR_ID",
        "GIRAFFE_DB_BASE_URL",
        "OPENCLAW_BASE_URL",
        "OLLAMA_BASE_URL",
        "AIVAN_LANGUAGE_SKILL_ENABLED",
        "AIVAN_LANGUAGE_SKILL_BASE_URL",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_BACKEND",
        "AIVAN_TRANSLATION_PROOFREAD_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIVAN_TENANT_API_KEYS", "{}")
    assert not all(readiness_checks().values())

    for value in ('{"": "key"}', '{"tenant": ""}', "not-json"):
        monkeypatch.setenv("AIVAN_TENANT_API_KEYS", value)
        checks = readiness_checks()
        assert checks["tenant_configured"] is False
        assert checks["api_auth_configured"] is False

    monkeypatch.setenv("AIVAN_CANDIDATE_SHA", "b" * 40)
    monkeypatch.setenv("AIVAN_DB_URL", "sqlite:///./data/aivan.db")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-1")
    monkeypatch.setenv("AIVAN_API_KEY", "injected")
    monkeypatch.setenv("AIVAN_UI_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "operator-1")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "sales,approver")
    monkeypatch.setenv("AIVAN_CORS_ORIGINS", "https://myaivan.com")
    monkeypatch.setenv("AIVAN_PORT", "8765")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("OPENCLAW_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("OPENCLAW_MOCK_MODE", "false")
    monkeypatch.setenv("AIVAN_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("AIVAN_NON_CHINA_EGRESS_POLICY", "abcdyi-sin")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_BASE_URL", "http://127.0.0.1:8788")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER", "ctranslate2")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_EXPECTED_MODEL", "opus-mt")
    monkeypatch.setenv("AIVAN_TRANSLATION_PROOFREAD_ENABLED", "true")
    assert all(readiness_checks().values())


def test_session_cookie_writer_rejects_unvalidated_values():
    import time

    import pytest
    from fastapi import Response

    from aivan.api.session_routes import _set_session_cookie

    with pytest.raises(RuntimeError, match="invalid signed session cookie"):
        _set_session_cookie(Response(), "unsafe; value", "x" * 43, int(time.time()) + 60)
    with pytest.raises(RuntimeError, match="invalid CSRF cookie"):
        _set_session_cookie(
            Response(),
            f"{'a' * 10}.{'b' * 43}",
            "unsafe; value",
            int(time.time()) + 60,
        )


def test_production_ui_login_requires_deployment_bound_tenant(monkeypatch):
    from fastapi import HTTPException

    from aivan.api.session_routes import _configured_ui_tenant

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.delenv("AIVAN_TENANT_ID", raising=False)
    with pytest.raises(HTTPException) as raised:
        _configured_ui_tenant()
    assert raised.value.status_code == 503
    assert raised.value.detail["error"] == "UI_TENANT_MISCONFIGURED"


def test_requested_role_is_canonicalized_from_server_allowlist(monkeypatch):
    from aivan.api.session_auth import configured_ui_identity

    monkeypatch.setenv("AIVAN_UI_ACTOR_ID", "operator-1")
    monkeypatch.setenv("AIVAN_UI_ALLOWED_ROLES", "admin,buyer")
    monkeypatch.setenv("AIVAN_UI_DEFAULT_ROLE", "admin")
    actor_id, roles, role = configured_ui_identity("BUYER")
    assert actor_id == "operator-1"
    assert roles == ("admin", "buyer")
    assert role == roles[1]
