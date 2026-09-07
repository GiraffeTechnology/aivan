from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client_and_session(monkeypatch, production_runtime_policy, ready_dependency_probes):
    from aivan.api import main
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

    monkeypatch.setenv("AIVAN_ENV", "production")
    monkeypatch.setenv("AIVAN_API_KEY", "stage2-secret")
    monkeypatch.setenv("AIVAN_TENANT_ID", "tenant-stage2")
    # Schema-startup behavior is tested by the migration-orchestrator suite.
    monkeypatch.setattr(main, "init_db", lambda: None)
    main.app.dependency_overrides[main.get_db] = override_db
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client, Session
    main.app.dependency_overrides.clear()
    engine.dispose()


def _headers(role: str, actor: str, trace: str) -> dict[str, str]:
    conversation_role = {
        "buyer": "buyer_thread",
        "supplier": "supplier_thread",
        "sales": "internal_thread",
        "procurement": "internal_thread",
        "qc": "qc_thread",
        "logistics": "logistics_thread",
        "approver": "approval_thread",
        "admin": "internal_thread",
    }[role]
    return {
        "X-AIVAN-API-Key": "stage2-secret",
        "X-AIVAN-Tenant-ID": "tenant-stage2",
        "X-AIVAN-Actor-ID": actor,
        "X-AIVAN-Role-Context": role,
        "X-AIVAN-Conversation-Role": conversation_role,
        "X-AIVAN-Execution-Mode": "update",
        "X-AIVAN-Trace-ID": trace,
    }


def _seed_project(Session, *, state: str) -> str:
    from aivan.db.repositories.project_repo import ProjectRepository

    with Session() as db:
        project = ProjectRepository(db).create(
            conversation_id=f"conversation-{state}",
            customer_id="buyer-1",
            tenant_id="tenant-stage2",
        )
        project.case_state = state
        project.requirement_json = {}
        db.commit()
        return project.project_id


def _transition(client, project_id: str, state: str, role: str, actor: str, trace: str):
    return client.post(
        f"/api/projects/{project_id}/transition",
        headers=_headers(role, actor, trace),
        json={"case_state": state},
    )


def test_sales_supplier_qc_logistics_and_approver_complete_legal_flow(client_and_session):
    from aivan.db.models.domain import AuditLogRecord
    from aivan.db.models.project import Project

    client, Session = client_and_session
    project_id = _seed_project(Session, state="inquiry")
    steps = [
        ("sourcing", "sales", "sales-1"),
        ("awaiting_supplier", "procurement", "procurement-1"),
        ("supplier_replied", "supplier", "supplier-1"),
        ("awaiting_approval", "sales", "sales-1"),
        ("approved", "approver", "approver-1"),
        ("qc", "qc", "qc-1"),
        ("logistics", "logistics", "logistics-1"),
        ("completed", "approver", "approver-1"),
    ]
    for index, (state, role, actor) in enumerate(steps, start=1):
        response = _transition(
            client, project_id, state, role, actor, f"trace-transition-{index}"
        )
        assert response.status_code == 200, response.text
        assert response.json()["after"] == state

    with Session() as db:
        assert db.get(Project, project_id).case_state == "completed"
        audits = (
            db.query(AuditLogRecord)
            .filter(AuditLogRecord.event_type == "CASE_STATE_TRANSITION")
            .all()
        )
        assert len(audits) == len(steps)
        assert all(a.actor_id and a.actor_role and a.source_trace_id for a in audits)
        assert all(a.authorization_basis == "deployment_api_key" for a in audits)


def test_illegal_transition_and_role_are_rejected_with_audit(client_and_session):
    from aivan.db.models.domain import AuditLogRecord
    from aivan.db.models.project import Project

    client, Session = client_and_session
    project_id = _seed_project(Session, state="approved")
    illegal_jump = _transition(
        client,
        project_id,
        "logistics",
        "logistics",
        "logistics-1",
        "trace-illegal-jump",
    )
    assert illegal_jump.status_code == 403
    assert illegal_jump.json()["detail"]["error"] == "INVALID_CASE_TRANSITION"

    forbidden_role = _transition(
        client, project_id, "qc", "buyer", "buyer-1", "trace-forbidden-role"
    )
    assert forbidden_role.status_code == 403
    assert forbidden_role.json()["detail"]["error"] == "CAPABILITY_FORBIDDEN"
    with Session() as db:
        assert db.get(Project, project_id).case_state == "approved"
        rejected = (
            db.query(AuditLogRecord)
            .filter(AuditLogRecord.event_type == "CASE_STATE_TRANSITION_REJECTED")
            .all()
        )
        assert len(rejected) == 2
        assert {row.source_trace_id for row in rejected} == {
            "trace-illegal-jump",
            "trace-forbidden-role",
        }


def test_buyer_cannot_update_strategy_but_sales_can(client_and_session):
    from aivan.db.models.domain import AuditLogRecord

    client, Session = client_and_session
    project_id = _seed_project(Session, state="inquiry")
    buyer = client.post(
        f"/api/projects/{project_id}/strategy",
        headers=_headers("buyer", "buyer-1", "trace-buyer-strategy"),
        json={"priority": "balanced"},
    )
    assert buyer.status_code == 403
    sales = client.post(
        f"/api/projects/{project_id}/strategy",
        headers=_headers("sales", "sales-1", "trace-sales-strategy"),
        json={"priority": "balanced"},
    )
    assert sales.status_code == 200, sales.text
    with Session() as db:
        rejection = (
            db.query(AuditLogRecord)
            .filter(AuditLogRecord.event_type == "PROJECT_ACTION_REJECTED")
            .one()
        )
        assert rejection.actor_role == "buyer"
        assert rejection.source_trace_id == "trace-buyer-strategy"
