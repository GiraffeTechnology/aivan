"""Tenant-bound binary evidence through the selected private data API only."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from urllib.parse import urlsplit

import httpx

from aivan.integrations.giraffe_db_auth import ServiceAuthError, service_auth_for_tenant
from aivan.integrations.transport_safety import reject_test_transport_in_production

_DEFAULT_TRANSPORT: httpx.BaseTransport | None = None
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


class AttachmentError(RuntimeError):
    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code, self.status = code, status


def safe_identity(value: str) -> str:
    if not _ID.fullmatch(value):
        raise AttachmentError("ATTACHMENT_IDENTITY_INVALID", 422)
    return value


class AttachmentClient:
    def __init__(self, tenant_id: str, trace_id: str, *, transport=None):
        self.tenant = safe_identity(tenant_id)
        self.trace = safe_identity(trace_id)
        self.base = os.environ.get("GIRAFFE_DB_BASE_URL", "").strip().rstrip("/")
        if not self.base:
            raise AttachmentError("ATTACHMENT_PROVIDER_NOT_CONFIGURED")
        try:
            self.auth = service_auth_for_tenant(self.tenant)
        except ServiceAuthError as exc:
            code = ("ATTACHMENT_PROVIDER_NOT_CONFIGURED" if exc.reason == "required"
                    else "ATTACHMENT_PROVIDER_AUTH_INVALID")
            raise AttachmentError(code) from None
        try:
            endpoint = urlsplit(self.base)
        except ValueError as exc:
            raise AttachmentError("ATTACHMENT_PROVIDER_CONFIGURATION_INVALID") from exc
        if (not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or endpoint.scheme not in {"http", "https"}
                or (endpoint.scheme == "http" and endpoint.hostname not in {"127.0.0.1", "localhost", "::1"})):
            raise AttachmentError("ATTACHMENT_PROVIDER_CONFIGURATION_INVALID")
        self.transport = transport if transport is not None else _DEFAULT_TRANSPORT
        reject_test_transport_in_production(self.transport, component="attachment")

    def _request(self, method, path, *, body=None, key=""):
        headers = {"X-Service-Tenant-ID": self.tenant, "X-Service-Auth": self.auth,
                   "X-AIVAN-Trace-ID": self.trace, "X-AIVAN-Correlation-ID": self.trace}
        if key:
            headers["Idempotency-Key"] = safe_identity(key)
        try:
            with httpx.Client(timeout=10, transport=self.transport, follow_redirects=False) as client:
                response = client.request(method, self.base + path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise AttachmentError("ATTACHMENT_INDETERMINATE_COMMIT" if method == "POST"
                                  else "ATTACHMENT_READBACK_UNAVAILABLE") from exc
        expected = {200, 201} if method == "POST" else {200}
        if response.status_code not in expected:
            if response.status_code in {401, 403, 404, 409, 413, 422}:
                raise AttachmentError(f"ATTACHMENT_PROVIDER_HTTP_{response.status_code}", response.status_code)
            raise AttachmentError("ATTACHMENT_INDETERMINATE_COMMIT" if method == "POST"
                                  else "ATTACHMENT_READBACK_UNAVAILABLE")
        return response

    def _metadata(self, response, case_id):
        try:
            data = response.json()
            if (not isinstance(data, dict) or data.get("tenant_id") != self.tenant
                    or data.get("procurement_case_id") != case_id):
                raise ValueError("binding")
            safe_identity(data.get("attachment_id", ""))
            return data
        except (ValueError, TypeError, AttachmentError) as exc:
            raise AttachmentError("ATTACHMENT_READBACK_INVALID") from exc

    def metadata(self, identity, case_id):
        path = f"/api/data/attachments/{safe_identity(identity)}"
        data = self._metadata(self._request("GET", path), case_id)
        if data["attachment_id"] != identity:
            raise AttachmentError("ATTACHMENT_READBACK_INVALID")
        return data

    def create(self, case_id, name, media_type, content, key, *, source_sha256=None, source_name_sha256=None):
        safe_identity(case_id)
        digest = hashlib.sha256(content).hexdigest()
        payload = {"procurement_case_id": case_id, "file_name": name,
                   "content_type": media_type, "content_base64": base64.b64encode(content).decode(),
                   "sha256": digest,
                   # Request correlation changes on retry; persisted operation lineage must not.
                   "source_trace_id": "attachment_" + hashlib.sha256(f"{self.tenant}:{key}".encode()).hexdigest()[:48]}
        lineage = {"source_sha256": source_sha256, "source_name_sha256": source_name_sha256}
        lineage = {field: value for field, value in lineage.items() if value is not None}
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in lineage.values()):
            raise AttachmentError("ATTACHMENT_SOURCE_HASH_INVALID", 422)
        payload.update(lineage)
        response = self._request("POST", "/api/data/attachments", body=payload, key=key)
        try:
            saved = self._metadata(response, case_id)
            readback = self.metadata(saved["attachment_id"], case_id)
        except AttachmentError as exc:
            raise AttachmentError("ATTACHMENT_INDETERMINATE_COMMIT") from exc
        expected = {"file_name": name, "content_type": media_type,
                    "size_bytes": len(content), "sha256": digest, **lineage}
        if saved != readback or any(readback.get(k) != v for k, v in expected.items()):
            raise AttachmentError("ATTACHMENT_INDETERMINATE_COMMIT")
        return readback

    def content(self, identity, case_id):
        metadata = self.metadata(identity, case_id)
        response = self._request("GET", f"/api/data/attachments/{safe_identity(identity)}/content")
        if (len(response.content) != metadata.get("size_bytes")
                or hashlib.sha256(response.content).hexdigest() != metadata.get("sha256")):
            raise AttachmentError("ATTACHMENT_CONTENT_INTEGRITY_MISMATCH")
        return metadata, response.content

    def list(self, case_id):
        safe_identity(case_id)
        response = self._request("GET", f"/api/data/procurement-cases/{case_id}/transaction-graph")
        try:
            graph = response.json()
            case = graph["procurement_case"]
            if case.get("tenant_id") != self.tenant or case.get("procurement_case_id") != case_id:
                raise ValueError("binding")
            items = graph["attachments"]
            if not isinstance(items, list):
                raise ValueError("shape")
            for item in items:
                if item.get("tenant_id") != self.tenant or item.get("procurement_case_id") != case_id:
                    raise ValueError("binding")
                safe_identity(item["attachment_id"])
            return items
        except (ValueError, TypeError, KeyError, AttributeError, AttachmentError) as exc:
            raise AttachmentError("ATTACHMENT_READBACK_INVALID") from exc
