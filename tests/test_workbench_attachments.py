"""Attachment consumer contract branches, not live-provider acceptance."""
import base64
import hashlib
import json

import httpx
import pytest

from tests.test_myaivan_workbench import _login, _seed_case, workbench  # noqa: F401


def test_upload_readback_and_content_use_trusted_case_mapping(workbench, monkeypatch):
    from aivan.integrations import attachment_client
    client, db = workbench
    login = _login(client)
    case = _seed_case(db, "operator-1", "attachment-case")
    case.requirement_json = {"giraffe_db_graph": {"procurement_case_id": "pc_1"}}
    db.commit()
    content = b"Need 100 cotton shirts delivered to Tokyo."
    digest = hashlib.sha256(content).hexdigest()
    calls = []
    metadata = {"attachment_id": "att_1", "tenant_id": "test_tenant",
                "procurement_case_id": "pc_1", "file_name": f"attachment-{digest[:12]}.txt",
                "content_type": "text/plain", "size_bytes": len(content), "sha256": digest,
                "content_path": "/api/data/attachments/att_1/content"}
    def handler(request):
        calls.append(request)
        assert request.headers["X-Service-Tenant-ID"] == "test_tenant"
        assert request.headers["X-Service-Auth"] == "controlled-fixture-key"
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["procurement_case_id"] == "pc_1"
            assert payload["file_name"] == metadata["file_name"]
            assert base64.b64decode(payload["content_base64"]) == content
            assert request.headers["Idempotency-Key"]
            return httpx.Response(201, json=metadata)
        if request.url.path.endswith("/content"):
            return httpx.Response(200, content=content, headers={"Content-Type": "text/plain"})
        return httpx.Response(200, json=metadata)
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "controlled-fixture-key")
    monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "false")
    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(handler))
    path = f"/api/workbench/cases/{case.project_id}/attachments"
    uploaded = client.post(path, headers={"X-AIVAN-CSRF": login["csrf_token"], "Idempotency-Key": "file-1"},
                           json={"file_name": "buyer.txt", "content_type": "text/plain",
                                 "content_base64": base64.b64encode(content).decode(), "sha256": digest})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["readback_verified"] is True
    assert uploaded.json()["processing_status"] == "canonical_text_available"
    assert uploaded.json()["canonical_text"] == content.decode()
    downloaded = client.get(uploaded.json()["download_path"])
    assert downloaded.content == content
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert len(calls) == 4


@pytest.mark.parametrize("status", [401, 403, 409, 422, 302, 503])
def test_provider_failure_is_distinct_and_never_upload_success(status, monkeypatch):
    from aivan.integrations.attachment_client import AttachmentClient, AttachmentError
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-key")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "http://other.test/"},
                              json={"raw": "sensitive-source"})
    consumer = AttachmentClient("test_tenant", "trace-1", transport=httpx.MockTransport(handler))
    with pytest.raises(AttachmentError) as error:
        consumer.create("pc_1", "attachment.txt", "text/plain", b"Hello", "key-1")
    assert error.value.status == (503 if status in {302, 503} else status)
    assert "sensitive-source" not in str(error.value)
    assert len(requests) == 1


def test_missing_case_graph_and_csrf_have_zero_provider_calls(workbench, monkeypatch):
    from aivan.integrations import attachment_client
    client, db = workbench
    login = _login(client)
    case = _seed_case(db, "operator-1", "missing-graph")
    def forbidden(request):
        pytest.fail("no provider call before local authorization and mapping")
    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(forbidden))
    body = {"file_name": "input.txt", "content_type": "text/plain",
            "content_base64": "SGVsbG8=", "sha256": hashlib.sha256(b"Hello").hexdigest()}
    path = f"/api/workbench/cases/{case.project_id}/attachments"
    assert client.post(path, json=body).status_code == 403
    assert client.post(path, json=body, headers={"X-AIVAN-CSRF": login["csrf_token"],
                                               "Idempotency-Key": "key-1"}).status_code == 409


@pytest.mark.parametrize("identity", [".", "..", "a/b", "%2f", "a\\b"])
def test_attachment_identity_cannot_escape_path(identity, monkeypatch):
    from aivan.integrations.attachment_client import AttachmentClient, AttachmentError
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-key")
    with pytest.raises(AttachmentError):
        AttachmentClient("test_tenant", "trace-1").metadata(identity, "pc_1")


def test_saved_operation_identity_does_not_change_with_request_trace(monkeypatch):
    from aivan.integrations.attachment_client import AttachmentClient
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-key")
    bodies = []
    def handler(request):
        if request.method == "POST":
            bodies.append(json.loads(request.content))
        body = bodies[-1]
        return httpx.Response(201 if request.method == "POST" else 200, json={
            **{k: v for k, v in body.items() if k != "content_base64"},
            "attachment_id": "att_replay", "tenant_id": "test_tenant", "size_bytes": 5})
    transport = httpx.MockTransport(handler)
    for trace in ("first-trace", "retry-trace"):
        AttachmentClient("test_tenant", trace, transport=transport).create("pc_1", "hello.txt", "text/plain", b"Hello", "same-key")
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("kind,content,expected", [
    ("text/html", b"<script>alert(1)</script>", 422),
    ("image/png", b"not-an-image", 422),
    ("image/jpeg", b"not-an-image", 422),
    ("text/plain", b"\x00invalid", 422),
    ("text/plain", b"\xffinvalid", 422),
])
def test_invalid_content_has_zero_provider_calls(workbench, monkeypatch, kind, content, expected):
    from aivan.integrations import attachment_client
    client, db = workbench
    login = _login(client)
    case = _seed_case(db, "operator-1", "invalid-file")
    case.requirement_json = {"giraffe_db_graph": {"procurement_case_id": "pc_1"}}
    db.commit()
    def forbidden(request):
        pytest.fail("invalid content must not reach provider")
    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(forbidden))
    response = client.post(f"/api/workbench/cases/{case.project_id}/attachments",
                           headers={"X-AIVAN-CSRF": login["csrf_token"], "Idempotency-Key": "invalid-1"},
                           json={"file_name": "input.txt", "content_type": kind,
                                 "content_base64": base64.b64encode(content).decode(),
                                 "sha256": hashlib.sha256(content).hexdigest()})
    assert response.status_code == expected


def test_image_has_no_invented_extracted_summary():
    from types import SimpleNamespace
    from aivan.api.attachment_routes import _input_content, Upload
    content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWV0AAAAASUVORK5CYII=")
    body = Upload(file_name="image.png", content_type="image/png",
                  content_base64=base64.b64encode(content).decode(), sha256=hashlib.sha256(content).hexdigest())
    saved, summary = _input_content(body, SimpleNamespace(tenant_id="test_tenant"))
    assert saved == content
    assert summary is None


def test_non_english_text_is_normalized_before_binary_persistence(monkeypatch):
    from types import SimpleNamespace
    from aivan.api import attachment_routes
    from aivan.api.attachment_routes import Upload
    raw = "\u9700\u8981100\u4ef6\u68c9\u886c\u886b".encode()
    calls = []
    def canonicalize(text, **kwargs):
        calls.append((text, kwargs))
        return {"normalize": {"canonical_language": "en", "canonical_text": "Need 100 cotton shirts"}}
    monkeypatch.setattr(attachment_routes, "canonicalize_rfq", canonicalize)
    body = Upload(file_name="source.txt", content_type="text/plain",
                  content_base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
    stored, text = attachment_routes._input_content(body, SimpleNamespace(tenant_id="test_tenant"))
    assert stored == b"Need 100 cotton shirts"
    assert raw not in stored
    assert calls[0][1]["tenant_id"] == "test_tenant"
    assert text == stored.decode()


@pytest.mark.parametrize("binding", [{"tenant_id": "other"}, {"procurement_case_id": "another-case"}])
def test_metadata_wrong_tenant_or_case_is_not_returned(binding, monkeypatch):
    from aivan.integrations.attachment_client import AttachmentClient, AttachmentError
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-key")
    data = {"attachment_id": "att_1", "tenant_id": "test_tenant", "procurement_case_id": "pc_1", **binding}
    consumer = AttachmentClient("test_tenant", "trace-1", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data)))
    with pytest.raises(AttachmentError, match="ATTACHMENT_READBACK_INVALID"):
        consumer.metadata("att_1", "pc_1")


def test_backup_reads_attachment_names_from_provider_or_reports_failure(workbench, monkeypatch):
    from aivan.integrations import attachment_client
    client, db = workbench
    _login(client)
    case = _seed_case(db, "operator-1", "attachment-export")
    case.requirement_json = {"giraffe_db_graph": {"procurement_case_id": "pc_1"}}
    db.commit()
    monkeypatch.setenv("GIRAFFE_DB_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", "fixture-key")
    item = {"tenant_id": "test_tenant", "procurement_case_id": "pc_1",
            "attachment_id": "att_1", "file_name": "attachment-123456789abc.txt"}
    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(200, json={"procurement_case": {
            "tenant_id": "test_tenant", "procurement_case_id": "pc_1"}, "attachments": [item]})))
    response = client.get(f"/api/workbench/cases/{case.project_id}/export")
    assert response.status_code == 200
    assert item["file_name"] in response.text
    assert "provider-verified references" in response.text
    monkeypatch.setattr(attachment_client, "_DEFAULT_TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(503)))
    assert client.get(f"/api/workbench/cases/{case.project_id}/export").status_code == 503


def test_image_preview_csp_does_not_relax_scripts_or_frames(workbench):
    client, _ = workbench
    policy = client.get("/app/").headers["Content-Security-Policy"]
    assert "img-src 'self' data: blob:" in policy
    assert "script-src 'self';" in policy
    assert "object-src 'none';" in policy
    assert "frame-ancestors 'none';" in policy
    assert "connect-src *" not in policy
