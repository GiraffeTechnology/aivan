import os
os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///:memory:")
os.environ.setdefault("AIVAN_REQUIRE_HUMAN_APPROVAL", "true")
# Sanctioned test-mode tenant fallback so service calls (GLTG v2 / giraffe-db)
# resolve a tenant in the suite without hardcoding a production placeholder.
# This gates ONLY tenant resolution — it never enables LLM mock fallback.
os.environ.setdefault("AIVAN_TEST_MODE", "true")
os.environ.setdefault("AIVAN_TEST_TENANT_ID", "test_tenant")
os.environ.setdefault("GLTG_SERVICE_AUTH_SECRET", "test-gltg-service-auth")
os.environ.setdefault("GPM_API_KEY", "test-gpm-api-key")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aivan.db.models import Base

from aivan.integrations import gltg_client as _gltg_client
from aivan.integrations import gpm_guidance_client as _gpm_guidance_client
from tests.gltg_fake import mock_transport as _gltg_mock_transport
from tests.gpm_guidance_fake import mock_transport as _gpm_mock_transport


@pytest.fixture(autouse=True)
def _language_intake_api_mock(monkeypatch):
    """Explicit synthetic contract for English-input unit tests, not live detection."""
    from aivan.integrations import language_skill_client
    from tests.language_skill_fake import mock_transport

    if os.environ.get("RUN_LANGUAGE_SKILL_INTEGRATION_TESTS") == "1":
        yield
        return
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
    language_skill_client.set_default_transport(mock_transport())
    try:
        yield
    finally:
        language_skill_client.set_default_transport(None)


@pytest.fixture(autouse=True)
def _gltg_api_mock():
    """Route all GLTG HTTP calls to an in-memory fake (no live server in unit tests).

    Disabled when RUN_GLTG_INTEGRATION_TESTS=1 so the live integration test hits
    a real GLTG server.
    """
    if os.environ.get("RUN_GLTG_INTEGRATION_TESTS") == "1":
        yield
        return
    _gltg_client.set_default_transport(_gltg_mock_transport())
    try:
        yield
    finally:
        _gltg_client.set_default_transport(None)


@pytest.fixture(autouse=True)
def _gpm_guidance_api_mock():
    """Route Stage 1 GPM guidance calls to a contract fixture in unit tests."""

    if os.environ.get("RUN_GPM_INTEGRATION_TESTS") == "1":
        yield
        return
    _gpm_guidance_client.set_default_transport(_gpm_mock_transport())
    try:
        yield
    finally:
        _gpm_guidance_client.set_default_transport(None)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def api_client():
    """FastAPI TestClient wired to an isolated in-memory DB (no API key)."""
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from aivan.api.main import app, get_db

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

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()
