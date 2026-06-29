import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from aivan.api.main import app, get_db
from aivan.db.models import Base
from aivan.db.models.intake import InquiryMessage, InquirySheet


@pytest.fixture
def db_override():
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

    os.environ.pop("AIVAN_API_KEY", None)
    app.dependency_overrides[get_db] = override_db
    try:
        yield Session
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest_asyncio.fixture
async def client(db_override):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_openclaw_event_persists_intake_before_downstream_failure(client, db_override, monkeypatch):
    import aivan.execution.rfq_execution as rfq_execution

    def fail_requirement(*args, **kwargs):
        raise RuntimeError("forced downstream requirement failure")

    monkeypatch.setattr(rfq_execution, "structure_customer_requirement_with_llm", fail_requirement)
    response = await client.post(
        "/api/openclaw/events",
        json={
            "source": "openclaw",
            "channel": "openclaw-weixin",
            "conversation_id": "conv-fail",
            "sender_id": "wx-buyer",
            "message_id": "msg-fail-1",
            "message_text": "询价5000件格子衬衫，45天交东京，高品质",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"

    db = db_override()
    try:
        sheets = db.query(InquirySheet).all()
        messages = db.query(InquiryMessage).all()
        assert len(sheets) == 1
        assert len(messages) == 1
        assert messages[0].sheet_id == sheets[0].id
        assert messages[0].raw_text == "询价5000件格子衬衫，45天交东京，高品质"
        assert messages[0].structured_json["quantity"] == 5000
    finally:
        db.close()
