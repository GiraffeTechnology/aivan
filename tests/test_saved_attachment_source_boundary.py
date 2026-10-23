"""Synthetic saved-TXT regressions; not private-provider or MySQL acceptance."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from aivan.db.models import Base
from aivan.db.repositories.domain_repo import CaseDomainRepository
from aivan.db.repositories.project_repo import ProjectRepository
from aivan.execution import saved_attachment_source as saved
from aivan.integrations import attachment_client
from aivan.openclaw.contracts import OpenClawEvent, SavedAttachmentSource


CONTENT = b"Request 100 cotton shirts; delivery within 12 days."
DIGEST = hashlib.sha256(CONTENT).hexdigest()


def event(**changes):
    fields = dict(
        tenant_id="tenant-fixture", source_trace_id="trace-fixture",
        idempotency_key="request-fixture", source="myaivan", channel="myaivan",
        conversation_id="conversation-fixture", sender_id="buyer-fixture",
        actor_id="buyer-fixture", authenticated_actor_id="staff-fixture",
        authenticated_actor_role="sales", business_role="buyer",
        conversation_role="buyer_thread", execution_mode="auto",
        authorization_basis="api_key", project_id="case-fixture",
        message_text="Use this saved specification.",
        saved_attachment_source={"attachment_id": "attachment-fixture", "sha256": DIGEST},
    )
    fields.update(changes)
    return OpenClawEvent(**fields)


def expect_error(status, code, operation):
    with pytest.raises(HTTPException) as caught:
        operation()
    assert caught.value.status_code == status
    assert caught.value.detail["error"] == code
    assert "test-only-service-auth" not in str(caught.value.detail)
    return caught.value


@pytest.fixture
def case_db():
    # This isolated unit fixture does not claim migration/MySQL validation.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    project = ProjectRepository(db).create(
        conversation_id="conversation-fixture", customer_id="buyer-fixture",
        customer_display_name="Synthetic buyer", channel="myaivan",
        tenant_id="tenant-fixture",
    )
    CaseDomainRepository(db).bind_inbound_event(
        project.project_id, event(project_id=project.project_id),
    )
    db.commit()
    try:
        yield db, project
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def provider(monkeypatch):
    calls = []
    state = {"content": CONTENT, "metadata_changes": {}, "status": 200}
    monkeypatch.setenv("AIVAN_ENV", "local")
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "https://attachment-fixture.invalid")
    monkeypatch.setenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON",
                       json.dumps({"tenant-fixture": "test-only-service-auth"}))
    monkeypatch.delenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", raising=False)

    def respond(request):
        calls.append(request)
        if state.get("timeout"):
            raise httpx.ReadTimeout("synthetic provider failure", request=request)
        if state["status"] != 200:
            return httpx.Response(state["status"], json={"private": "never return raw response"},
                                  headers={"Location": "https://forbidden-redirect.invalid"})
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=state.get("returned_content", state["content"]))
        metadata = dict(
            attachment_id="attachment-fixture", tenant_id="tenant-fixture",
            procurement_case_id="provider-case-fixture", content_type="text/plain",
            size_bytes=len(state["content"]), sha256=hashlib.sha256(state["content"]).hexdigest(),
        )
        metadata.update(state["metadata_changes"])
        return httpx.Response(200, json=metadata)

    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(respond))
    project = SimpleNamespace(requirement_json={
        "giraffe_db_graph": {"procurement_case_id": "provider-case-fixture"}})
    return calls, state, project


@pytest.mark.parametrize("source", [
    {"attachment_id": "..", "sha256": DIGEST},
    {"attachment_id": "../escape", "sha256": DIGEST},
    {"attachment_id": "a%2fescape", "sha256": DIGEST},
    {"attachment_id": "attachment-fixture", "sha256": "g" * 64},
    {"attachment_id": "attachment-fixture", "sha256": DIGEST, "verification": "trusted"},
])
def test_source_dto_rejects_paths_invalid_digests_and_verification_assertions(source):
    with pytest.raises(ValidationError):
        SavedAttachmentSource(**source)


def test_no_saved_source_is_a_noop():
    original = event(saved_attachment_source=None)
    assert saved.authorize_saved_attachment(original, None) is None
    assert saved.resolve_saved_attachment(original, None) is original
    assert saved.source_request_fingerprint(original) is None


def test_generic_attachment_cannot_claim_provider_verification():
    original = event(attachments=[{"source_type": saved.SOURCE_KIND}])
    error = expect_error(422, "ATTACHMENT_SOURCE_MARKER_RESERVED",
                         lambda: saved.authorize_saved_attachment(original, None))
    assert error.detail["trace_id"] == original.source_trace_id


@pytest.mark.parametrize("field", [
    "tenant_id", "project_id", "authenticated_actor_id",
    "authenticated_actor_role", "authorization_basis",
])
def test_missing_trusted_context_fails_before_case_or_provider_read(field):
    original = event(**{field: ""})
    expect_error(403, "ATTACHMENT_SOURCE_TRUSTED_CONTEXT_REQUIRED",
                 lambda: saved.authorize_saved_attachment(original, None))


@pytest.mark.parametrize("role", ["supplier", "auditor", "approver"])
def test_non_inquiry_role_is_not_implicitly_upgraded(role):
    expect_error(403, "ATTACHMENT_SOURCE_USE_FORBIDDEN",
                 lambda: saved.authorize_saved_attachment(event(authenticated_actor_role=role), None))


def test_internal_actor_can_read_same_tenant_case_without_mutating_it(case_db):
    db, project = case_db
    result = saved.authorize_saved_attachment(event(project_id=project.project_id), db)
    assert result is project
    assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other-tenant"},
    {"authenticated_actor_role": "buyer", "authenticated_actor_id": "stranger-fixture"},
])
def test_other_tenant_or_non_member_cannot_read_case(case_db, changes):
    db, project = case_db
    expect_error(404, "CASE_NOT_FOUND", lambda: saved.authorize_saved_attachment(
        event(project_id=project.project_id, **changes), db))
    assert not db.new and not db.dirty and not db.deleted


def test_buyer_requires_active_authenticated_membership(case_db):
    db, project = case_db
    original = event(project_id=project.project_id, authenticated_actor_id="buyer-fixture",
                     authenticated_actor_role="buyer")
    assert saved.authorize_saved_attachment(original, db) is project


@pytest.mark.parametrize("changes", [
    {"tenant_id": "other-tenant"}, {"project_id": "other-case"},
    {"authenticated_actor_id": "other-actor"}, {"authenticated_actor_role": "admin"},
    {"channel_account_id": "other-channel"}, {"message_text": "Changed request"},
    {"saved_attachment_source": {"attachment_id": "other-attachment", "sha256": DIGEST}},
])
def test_replay_fingerprint_binds_business_identity_and_source(changes):
    previous = saved.source_request_fingerprint(event())
    current = event(**changes)
    assert saved.source_request_fingerprint(current) != previous
    receipt = SimpleNamespace(result_json={saved.RECEIPT_FIELD: previous})
    expect_error(409, "ATTACHMENT_SOURCE_REQUEST_CONFLICT", lambda: saved.validate_source_replay(
        receipt, saved.source_request_fingerprint(current), current))


def test_correlation_change_does_not_invalidate_identical_replay():
    first, retry = event(), event(source_trace_id="trace-retry-fixture")
    fingerprint = saved.source_request_fingerprint(first)
    assert saved.source_request_fingerprint(retry) == fingerprint
    assert saved.validate_source_replay(
        SimpleNamespace(result_json={saved.RECEIPT_FIELD: fingerprint}), fingerprint, retry) is None


def test_preexisting_unbound_receipt_is_not_accepted_as_source_replay():
    expect_error(409, "ATTACHMENT_SOURCE_REQUEST_CONFLICT", lambda: saved.validate_source_replay(
        SimpleNamespace(result_json=None), saved.source_request_fingerprint(event()), event()))


def test_success_reads_actual_client_contract_and_does_not_mutate_original(provider):
    calls, _, project = provider
    original = event()
    result = saved.resolve_saved_attachment(original, project)
    assert result is not original and original.attachments == []
    assert original.message_text == "Use this saved specification."
    assert CONTENT.decode() in result.message_text
    assert result.attachments == [{
        "source_type": saved.SOURCE_KIND, "attachment_id": "attachment-fixture",
        "sha256": DIGEST, "procurement_case_id": "provider-case-fixture",
        "content_type": "text/plain", "size_bytes": len(CONTENT),
        "verification": "provider_content_readback",
    }]
    assert len(calls) == 3 and all(request.method == "GET" for request in calls)
    for request in calls:
        assert request.headers["X-Service-Auth"] == "test-only-service-auth"
        assert request.headers["X-Service-Tenant-ID"] == "tenant-fixture"
        assert request.headers["X-AIVAN-Correlation-ID"] == "trace-fixture"


def test_missing_persisted_case_does_not_contact_provider(provider):
    calls, _, _ = provider
    expect_error(409, "ATTACHMENT_PERSISTED_CASE_REQUIRED", lambda: saved.resolve_saved_attachment(
        event(), SimpleNamespace(requirement_json={})))
    assert calls == []


@pytest.mark.parametrize("changes,status,code", [
    ({"tenant_id": "other-tenant"}, 503, "ATTACHMENT_READBACK_INVALID"),
    ({"procurement_case_id": "other-case"}, 503, "ATTACHMENT_READBACK_INVALID"),
    ({"sha256": "0" * 64}, 409, "ATTACHMENT_SOURCE_CHANGED"),
    ({"content_type": "application/pdf"}, 422, "ATTACHMENT_SOURCE_TEXT_REQUIRED"),
    ({"size_bytes": 0}, 422, "ATTACHMENT_SOURCE_TEXT_REQUIRED"),
    ({"size_bytes": True}, 422, "ATTACHMENT_SOURCE_TEXT_REQUIRED"),
    ({"size_bytes": 65537}, 422, "ATTACHMENT_SOURCE_TEXT_REQUIRED"),
])
def test_invalid_provider_metadata_never_fetches_content(provider, changes, status, code):
    calls, state, project = provider
    state["metadata_changes"] = changes
    expect_error(status, code, lambda: saved.resolve_saved_attachment(event(), project))
    assert len(calls) == 1


def test_changed_content_is_rejected_by_real_attachment_client(provider):
    calls, state, project = provider
    state["returned_content"] = b"changed provider bytes"
    expect_error(503, "ATTACHMENT_CONTENT_INTEGRITY_MISMATCH",
                 lambda: saved.resolve_saved_attachment(event(), project))
    assert len(calls) == 3 and all(request.method == "GET" for request in calls)


@pytest.mark.parametrize("content,code", [
    (b"\xff", "ATTACHMENT_SOURCE_UTF8_REQUIRED"),
    (b"  \n", "ATTACHMENT_SOURCE_TEXT_INVALID"),
    (b"bad\x00text", "ATTACHMENT_SOURCE_TEXT_INVALID"),
])
def test_invalid_text_never_becomes_verified_event_content(provider, content, code):
    _, state, project = provider
    state["content"] = content
    original = event(saved_attachment_source={
        "attachment_id": "attachment-fixture", "sha256": hashlib.sha256(content).hexdigest()})
    expect_error(422, code, lambda: saved.resolve_saved_attachment(original, project))
    assert original.attachments == []


@pytest.mark.parametrize("status", [401, 403, 404, 409, 413, 422, 302, 500, 503])
def test_provider_failure_or_redirect_does_not_continue_or_expose_body(provider, status):
    calls, state, project = provider
    state["status"] = status
    expected_status = status if status in {401, 403, 404, 409, 413, 422} else 503
    code = f"ATTACHMENT_PROVIDER_HTTP_{status}" if status in {401, 403, 404, 409, 413, 422} else "ATTACHMENT_READBACK_UNAVAILABLE"
    error = expect_error(expected_status, code, lambda: saved.resolve_saved_attachment(event(), project))
    assert "never return raw response" not in str(error.detail)
    assert len(calls) == 1


def test_provider_timeout_is_stable_and_read_only(provider):
    calls, state, project = provider
    state["timeout"] = True
    expect_error(503, "ATTACHMENT_READBACK_UNAVAILABLE",
                 lambda: saved.resolve_saved_attachment(event(), project))
    assert len(calls) == 1 and calls[0].method == "GET"


def test_missing_service_credential_makes_zero_http_calls(provider, monkeypatch):
    calls, _, project = provider
    monkeypatch.delenv("GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON")
    expect_error(503, "ATTACHMENT_PROVIDER_NOT_CONFIGURED",
                 lambda: saved.resolve_saved_attachment(event(), project))
    assert calls == []
