import os
import logging
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def _get_db_url() -> str:
    configured = os.environ.get("AIVAN_DB_URL", "").strip()
    if configured:
        return configured
    if os.environ.get("AIVAN_ENV", "local").strip().lower() == "production":
        raise RuntimeError(
            "AIVAN_DB_URL is required in production and must be injected by the "
            "authorized secret/configuration store."
        )

    canonical = Path("data/aivan.db")
    legacy = Path("data/aiven.db")
    if canonical.exists() and legacy.exists():
        raise RuntimeError(
            "Both data/aivan.db and legacy data/aiven.db exist; set AIVAN_DB_URL "
            "explicitly to prevent a split database."
        )
    if legacy.exists():
        logger.warning(
            "Using legacy data/aiven.db for compatibility; set AIVAN_DB_URL and "
            "migrate it to data/aivan.db during an authorized maintenance window."
        )
        return "sqlite:///./data/aiven.db"
    return "sqlite:///./data/aivan.db"

def _make_engine():
    url = _get_db_url()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        os.makedirs("data", exist_ok=True)
    engine = create_engine(url, connect_args=connect_args, echo=False)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine

_engine = None
_SessionLocal = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine

def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal

def get_db() -> Session:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def db_session() -> Session:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    from aivan.db.models import Base
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
