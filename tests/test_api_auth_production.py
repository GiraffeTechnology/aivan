"""Production auth fail-closed tests (PRD §12, §18.6)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    from aivan.api.main import app, get_db
    from aivan.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.get(k) for k in ("AIVAN_ENV", "AIVAN_API_KEY", "AIVAN_AUTH_SECRET")}
    for k in saved:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _rejected(status: int) -> bool:
    return status in (401, 403, 503)


def test_production_without_api_key_rejects_protected_routes(client):
    os.environ["AIVAN_ENV"] = "production"
    assert _rejected(client.get("/api/projects").status_code)
    assert _rejected(client.post("/api/openclaw/events", json={"channel": "t"}).status_code)


def test_production_health_still_open(client):
    os.environ["AIVAN_ENV"] = "production"
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_projects_list_requires_auth_in_production(client):
    os.environ["AIVAN_ENV"] = "production"
    assert _rejected(client.get("/api/projects").status_code)


def test_suppliers_import_requires_auth_in_production(client):
    os.environ["AIVAN_ENV"] = "production"
    assert _rejected(client.post("/api/suppliers/import", json={"csv_content": "x"}).status_code)


def test_platform_mutation_requires_auth_in_production(client):
    os.environ["AIVAN_ENV"] = "production"
    assert _rejected(client.post("/api/platforms/whitelist", json={"domain": "example.com"}).status_code)


def test_user_preferences_requires_auth_in_production(client):
    os.environ["AIVAN_ENV"] = "production"
    assert _rejected(
        client.post(
            "/api/user-preferences/update",
            json={"user_id": "u", "preference_type": "p", "value": {}},
        ).status_code
    )


def test_local_mode_can_run_without_auth(client):
    os.environ["AIVAN_ENV"] = "local"
    # No secret configured; local mode serves protected routes openly.
    assert client.get("/api/projects").status_code == 200


def test_production_with_api_key_allows_authenticated(client):
    os.environ["AIVAN_ENV"] = "production"
    os.environ["AIVAN_API_KEY"] = "prod-secret"
    ok = client.get("/api/projects", headers={"X-AIVAN-API-Key": "prod-secret"})
    assert ok.status_code == 200
    bad = client.get("/api/projects")
    assert bad.status_code == 401
