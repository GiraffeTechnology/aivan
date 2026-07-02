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
