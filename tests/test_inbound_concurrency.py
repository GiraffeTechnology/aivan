"""Controlled transaction interleavings; SQLite unit evidence, not MySQL acceptance."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from aivan.db.models import Base, ExecutionEventRecord, ProcessedInboundEvent
from aivan.db.repositories.inbound_event_repo import InboundEventRepository
from aivan.execution.rfq_execution import create_rfq_from_event
from tests.test_inbound_idempotency import _event


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'receipts.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.mark.parametrize("via_relay", [False, True])
def test_stale_absent_receipt_cannot_repeat_requirement_events(tmp_path, monkeypatch, via_relay):
    from aivan.api.main import app, get_db
    from aivan.db.models import AuditLogRecord

    engine = create_engine(f"sqlite:///{tmp_path / 'interleaving.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    readers = Barrier(2)
    first_completed = Event()
    ordinal_lock = Lock()
    ordinal = 0
    original_get = InboundEventRepository.get

    def controlled_get(repo, identity):
        nonlocal ordinal
        observed = original_get(repo, identity)
        if "initial_read" not in repo.db.info:
            with ordinal_lock:
                lane = ordinal
                ordinal += 1
            repo.db.info["initial_read"] = lane
            assert observed is None  # Both actual SELECTs observed absence.
            readers.wait(timeout=15)
            if lane == 1:
                assert first_completed.wait(timeout=25)
        return observed

    monkeypatch.setattr(InboundEventRepository, "get", controlled_get)

    def request_db():
        with sessions() as db:
            yield db
            if db.info.get("initial_read") == 0:
                first_completed.set()

    client = None
    if via_relay:
        monkeypatch.setenv("AIVAN_API_KEY", "")
        app.dependency_overrides[get_db] = request_db
        client = TestClient(app, raise_server_exceptions=False)

    def invoke():
        if client is not None:
            response = client.post("/api/relay/inbound", json=_event().model_dump(), headers={
                "X-AIVAN-Tenant-ID": "tenant-a", "Idempotency-Key": "controlled-replay",
            })
            assert response.status_code == 200, response.text
            return response.json()
        with sessions() as db:
            result = create_rfq_from_event(_event(idempotency_key="controlled-replay"), db)
            if db.info["initial_read"] == 0:
                first_completed.set()
            return result.model_dump()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [task.result(timeout=40) for task in (pool.submit(invoke), pool.submit(invoke))]
        assert first["project_id"] == second["project_id"]
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(ProcessedInboundEvent)) == 1
            for event_type in ("PROJECT_CREATED", "CANONICAL_INBOUND_MESSAGE",
                               "EXECUTION_GATE_BLOCKED", "USER_CONTROL_CONFIRMATION_REQUESTED"):
                assert db.scalar(select(func.count()).select_from(ExecutionEventRecord).where(
                    ExecutionEventRecord.event_type == event_type,
                )) == 1, event_type
            if via_relay:
                assert sorted([first["idempotent_replay"], second["idempotent_replay"]]) == [False, True]
                assert db.scalar(select(func.count()).select_from(AuditLogRecord).where(
                    AuditLogRecord.event_type == "RELAY_INBOUND_ACCEPTED",
                )) == 1
    finally:
        first_completed.set()
        if client is not None:
            client.close()
            app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_inflight_claim_blocks_second_session_before_business(sessions, monkeypatch):
    from aivan.execution import rfq_execution

    entered, release = Event(), Event()
    original = rfq_execution._create_rfq_from_event_inner
    calls = []

    def controlled_inner(*args, **kwargs):
        calls.append("business")
        entered.set()
        assert release.wait(timeout=15)
        return original(*args, **kwargs)

    monkeypatch.setattr(rfq_execution, "_create_rfq_from_event_inner", controlled_inner)

    def first_request():
        with sessions() as db:
            return create_rfq_from_event(_event(), db)

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(first_request)
        try:
            assert entered.wait(timeout=15)
            with sessions() as db, pytest.raises(HTTPException) as denied:
                create_rfq_from_event(_event(), db)
            assert denied.value.status_code == 409
            assert denied.value.detail["code"] == "INBOUND_OUTCOME_UNCONFIRMED"
            assert calls == ["business"]
        finally:
            release.set()
        result = first.result(timeout=20)
    with sessions() as db:
        assert create_rfq_from_event(_event(), db).model_dump() == result.model_dump()
    assert calls == ["business"]


def test_failed_after_committed_effects_remains_blocked_after_session_restart(sessions, monkeypatch):
    from aivan.execution import rfq_execution

    original = rfq_execution._create_rfq_from_event_inner

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic interruption after workflow commit")

    monkeypatch.setattr(rfq_execution, "_create_rfq_from_event_inner", interrupted)
    with sessions() as db, pytest.raises(RuntimeError):
        create_rfq_from_event(_event(), db)
    with sessions() as db:
        before = db.scalar(select(func.count()).select_from(ExecutionEventRecord))
        assert before > 0
        with pytest.raises(HTTPException) as denied:
            create_rfq_from_event(_event(), db)
        assert denied.value.status_code == 409
        assert "synthetic interruption" not in str(denied.value.detail)
        assert db.scalar(select(func.count()).select_from(ExecutionEventRecord)) == before


def test_completed_receipt_replays_after_session_restart_without_language_call(sessions, monkeypatch):
    with sessions() as db:
        original = create_rfq_from_event(_event(), db)

    def forbidden(*args, **kwargs):
        pytest.fail("Completed replay must not call translation or business execution")

    monkeypatch.setattr("aivan.execution.rfq_execution.canonicalize_rfq", forbidden)
    monkeypatch.setattr("aivan.execution.rfq_execution._create_rfq_from_event_inner", forbidden)
    with sessions() as db:
        assert create_rfq_from_event(_event(), db).model_dump() == original.model_dump()


@pytest.mark.parametrize("path", ["/invoke", "/api/openclaw/events", "/api/skill/invoke",
                                  "/api/rfq/create-from-event"])
def test_pending_claim_has_truthful_http_error_and_no_events(api_client, path):
    from aivan.api.main import get_db
    from aivan.db.repositories.inbound_event_repo import build_inbound_idempotency_key

    dependency = api_client.app.dependency_overrides[get_db]()
    db = next(dependency)
    key = build_inbound_idempotency_key(
        tenant_id="tenant-a", source="", channel="", channel_account_id="",
        conversation_id="", message_id="", explicit_idempotency_key="pending-test",
    )
    InboundEventRepository(db).claim(key, tenant_id="tenant-a")
    before = db.scalar(select(func.count()).select_from(ExecutionEventRecord))
    response = api_client.post(path, json=_event().model_dump(), headers={
        "X-AIVAN-Tenant-ID": "tenant-a", "Idempotency-Key": "pending-test",
        "X-AIVAN-Trace-ID": "pending-trace",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "INBOUND_OUTCOME_UNCONFIRMED"
    assert response.json()["detail"]["trace_id"] == "pending-trace"
    assert db.scalar(select(func.count()).select_from(ExecutionEventRecord)) == before
    dependency.close()
