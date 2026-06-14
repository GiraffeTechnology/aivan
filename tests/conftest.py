import os
os.environ.setdefault("AIVEN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVEN_DB_URL", "sqlite:///:memory:")
os.environ.setdefault("AIVEN_REQUIRE_HUMAN_APPROVAL", "true")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aiven.db.models import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
