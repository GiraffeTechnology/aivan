"""AIVAN-002: GET /api/openclaw/drafts/{draft_id} single-draft endpoint.

Coverage:
1. existing draft_id -> 200 with the full draft body
2. unknown draft_id -> 404 with a structured JSON error
3. returned fields are complete (draft_id, status, message_text, ...)
"""
from __future__ import annotations
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client_and_session():
    """TestClient plus a Session factory sharing one in-memory SQLite DB."""
    from aivan.api.main import app, get_db
    from aivan.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        yield c, Session
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture(autouse=True)
def clear_api_key():
    os.environ.pop("AIVAN_API_KEY", None)
    yield
    os.environ.pop("AIVAN_API_KEY", None)


def _seed_draft(Session) -> str:
    from aivan.db.repositories.draft_repo import DraftRepository

    db = Session()
    try:
        repo = DraftRepository(db)
        draft = repo.create(
            project_id="proj_get_001",
            data={
                "message_text": "Quote request for 1000 industrial gloves",
                "channel": "wechat",
                "target_peer_id": "buyer-001",
                "target_role": "buyer",
                "created_by_agent": "trade_salesperson_agent",
            },
        )
        db.commit()
        return draft.draft_id
    finally:
        db.close()


def test_get_draft_by_id_returns_200(client_and_session):
    client, Session = client_and_session
    draft_id = _seed_draft(Session)
    resp = client.get(f"/api/openclaw/drafts/{draft_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["draft_id"] == draft_id


def test_get_draft_nonexistent_returns_404(client_and_session):
    client, _ = client_and_session
    resp = client.get("/api/openclaw/drafts/nonexistent-draft-id-xyz")
    assert resp.status_code == 404
    data = resp.json()
    # Structured JSON error, not HTML.
    assert "detail" in data
    assert data["detail"]["error"] == "not_found"
    assert data["detail"]["draft_id"] == "nonexistent-draft-id-xyz"


def test_get_draft_fields_complete(client_and_session):
    client, Session = client_and_session
    draft_id = _seed_draft(Session)
    resp = client.get(f"/api/openclaw/drafts/{draft_id}")
    data = resp.json()
    assert data["draft_id"] == draft_id
    assert "status" in data
    assert data["message_text"] == "Quote request for 1000 industrial gloves"
    assert data["channel"] == "wechat"
    assert data["status"] == "pending_approval"


def test_get_draft_requires_api_key_when_configured(client_and_session):
    """Endpoint is guarded by the same API-key dependency as its siblings."""
    client, Session = client_and_session
    draft_id = _seed_draft(Session)
    os.environ["AIVAN_API_KEY"] = "secret-key-abc"
    resp = client.get(f"/api/openclaw/drafts/{draft_id}")
    assert resp.status_code == 401
