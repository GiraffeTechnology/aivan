import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

def _get_db_url() -> str:
    url = os.environ.get("AIVAN_DB_URL", "sqlite:///./data/aiven.db")
    return url

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
