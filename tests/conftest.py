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

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aivan.db.models import Base

from aivan.integrations import gltg_client as _gltg_client
from tests.gltg_fake import mock_transport as _gltg_mock_transport


@pytest.fixture
def production_runtime_policy(monkeypatch):
    """Install the explicit fail-closed Stage A production boundary for a test."""
    # The suite-wide GLTG fake is safe for local tests but must never remain
    # active once a test intentionally crosses into the production profile.
    _gltg_client.set_default_transport(None)
    values = {
        "AIVAN_PRODUCT_ROLE": "monitoring_takeover_control_plane",
        "AIVAN_BUSINESS_FACT_AUTHORITY": "giraffe-db",
        "AIVAN_LOCAL_STATE_SCOPE": "control_audit_cache_only",
        "AIVAN_REQUIRE_HUMAN_APPROVAL": "true",
        "AIVAN_ALLOW_STUB_SUPPLIERS": "false",
        "OPENCLAW_MOCK_MODE": "false",
        "AIVAN_LLM_PROVIDER": "ollama",
        "GPM_LLM_RUNTIME_MODE": "live",
        "AIVAN_WEB_SEARCH_PROVIDER": "openclaw_search",
        "AIVAN_ALIBABA_MODE": "official_api",
        "AIVAN_LANGUAGE_SKILL_EXPECTED_PROVIDER": "ctranslate2",
        "AIVAN_EXTERNAL_MODEL_API_AUTO_ALLOWED": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in (
        "AIVAN_CODE_GENERATION_ENABLED",
        "AIVAN_CODE_EXECUTION_ENABLED",
        "AIVAN_REPOSITORY_WRITE_ENABLED",
        "AIVAN_GIT_OPERATIONS_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


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
