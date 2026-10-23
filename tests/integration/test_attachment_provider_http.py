"""Selected-provider HTTP/migration/restart; never a MySQL/full-chain claim.

Configure its actual canonical-language API as well as the provider source.
For real Aivan language HTTP, also enable RUN_LANGUAGE_SKILL_INTEGRATION_TESTS
and configure AIVAN_LANGUAGE_SKILL_BASE_URL instead of the unit transport.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import sys
import time
import zlib

import httpx
import pytest

from tests.test_myaivan_workbench import _login, _seed_case, workbench  # noqa: F401


def test_aivan_attachment_routes_selected_provider_http_and_restart(workbench, tmp_path, monkeypatch):
    source = os.environ.get("AIVAN_ATTACHMENT_PROVIDER_SOURCE", "")
    if not source:
        pytest.skip("selected provider source is not configured; no real integration claim")
    provider = Path(source).resolve()
    assert (provider / "alembic.ini").is_file()
    provider_python = os.environ.get("AIVAN_ATTACHMENT_PROVIDER_PYTHON", sys.executable)
    # This test's real provider is loopback, not the host's outbound proxy.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    secret = secrets.token_hex(32)
    other_secret = secrets.token_hex(32)
    environment = {**os.environ, "PYTHONPATH": str(provider / "src"),
                   "GIRAFFE_DB_DATABASE_URL": f"sqlite+pysqlite:///{(tmp_path / 'provider.sqlite3').as_posix()}",
                   "GIRAFFE_DB_ENVIRONMENT": "production",
                   "GIRAFFE_DB_REQUIRE_LANGUAGE_SKILL": "true",
                   "GIRAFFE_DB_TENANT_SERVICE_AUTH_JSON": json.dumps({"test_tenant": secret, "other_tenant": other_secret})}
    migrated = subprocess.run([provider_python, "-m", "alembic", "upgrade", "head"],
                              cwd=provider, env=environment, capture_output=True, timeout=60)
    assert migrated.returncode == 0, "isolated provider migration failed (output withheld)"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    headers = {"X-Service-Tenant-ID": "test_tenant", "X-Service-Auth": secret}
    def start():
        process = subprocess.Popen([provider_python, "-m", "uvicorn", "giraffe_db.api.main:app",
                                    "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                                   cwd=provider, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        observed_status = None
        while time.monotonic() < deadline:
            assert process.poll() is None, "isolated provider exited before readiness"
            try:
                observed_status = httpx.get(base + "/api/data/schema-version", headers=headers, timeout=1, trust_env=False).status_code
                if observed_status == 200:
                    return process
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        process.terminate()
        process.wait(timeout=10)
        pytest.fail(f"isolated provider readiness timed out; last status={observed_status}")
    def stop(process):
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    process = start()
    try:
        def create(path, body, key):
            response = httpx.post(base + path, json=body, headers={**headers, "Idempotency-Key": key}, timeout=5)
            try:
                pending = [response.json()]
            except ValueError:
                pending = []
            codes = set()
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    for field, code in value.items():
                        if (field in {"error", "code", "type"} and isinstance(code, str)
                                and code not in {secret, other_secret}
                                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", code)):
                            codes.add(code)
                        elif isinstance(code, (dict, list)):
                            pending.append(code)
                elif isinstance(value, list):
                    pending.extend(value)
            assert response.status_code in {200, 201}, f"provider setup status {response.status_code}; codes={sorted(codes)}"
            return response.json()
        buyer = create("/api/data/buyers", {"buyer_name": "Synthetic Attachment Buyer"}, "attachment:buyer")
        # Real tenant-bound credentials, not a shared-secret or anonymous bypass.
        for tenant, wrong_secret in (("test_tenant", other_secret), ("other_tenant", secret)):
            denied = httpx.post(base + "/api/data/buyers", json={"buyer_name": "Must Not Be Created"},
                                headers={"X-Service-Tenant-ID": tenant, "X-Service-Auth": wrong_secret}, timeout=5)
            assert denied.status_code == 403
        private_case = create("/api/data/procurement-cases", {"buyer_id": buyer["buyer_id"], "status": "open"}, "attachment:case")
        client, db = workbench
        login = _login(client)
        case = _seed_case(db, "operator-1", "real-attachment-http")
        case.requirement_json = {"giraffe_db_graph": {"procurement_case_id": private_case["procurement_case_id"]}}
        db.commit()
        monkeypatch.setenv("GIRAFFE_DB_BASE_URL", base)
        monkeypatch.setenv("GIRAFFE_DB_SERVICE_AUTH_SECRET", secret)
        monkeypatch.setenv("AIVAN_LANGUAGE_SKILL_ENABLED", "true")
        raw = (b"We need 100 cotton shirts to be delivered to Tokyo within 45 days. "
               b"Please review our purchase requirements and confirm the available sizes.")
        body = {"file_name": "inquiry.txt", "content_type": "text/plain",
                "content_base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
        path = f"/api/workbench/cases/{case.project_id}/attachments"
        trusted = {"X-AIVAN-CSRF": login["csrf_token"], "Idempotency-Key": "real-file-1"}
        uploaded = client.post(path, json=body, headers=trusted)
        assert uploaded.status_code == 200, uploaded.text
        saved = uploaded.json()
        assert saved["readback_verified"] is True
        # The language service may normalize even already-English input. The
        # persisted/downloaded bytes are the returned canonical text, not raw.
        canonical_text = saved["canonical_text"]
        assert isinstance(canonical_text, str) and canonical_text.strip()
        canonical_bytes = canonical_text.encode("utf-8")
        replay = client.post(path, json=body, headers=trusted)
        assert replay.status_code == 200
        assert replay.json()["attachment_id"] == saved["attachment_id"]
        changed_text = (b"We would like to change the requested quantity to 200 cotton shirts for delivery "
                        b"to Tokyo within 45 days. Please confirm the updated purchase requirements.")
        changed = {**body, "content_base64": base64.b64encode(changed_text).decode(),
                   "sha256": hashlib.sha256(changed_text).hexdigest()}
        assert client.post(path, json=changed, headers=trusted).status_code == 409
        corrupt_image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWV0AAAAASUVORK5CYII=")
        invalid_image = client.post(path, headers={**trusted, "Idempotency-Key": "real-bad-image-1"}, json={
            "file_name": "sample.png", "content_type": "image/png",
            "content_base64": base64.b64encode(corrupt_image).decode(), "sha256": hashlib.sha256(corrupt_image).hexdigest()})
        assert invalid_image.status_code == 422
        assert [item["attachment_id"] for item in client.get(path).json()["items"]] == [saved["attachment_id"]]

        def png_chunk(kind, content):
            return (struct.pack(">I", len(content)) + kind + content
                    + struct.pack(">I", zlib.crc32(kind + content)))
        image = (b"\x89PNG\r\n\x1a\n"
                 + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
                 + png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff\xff"))
                 + png_chunk(b"IEND", b""))
        image_response = client.post(path, headers={**trusted, "Idempotency-Key": "real-image-1"}, json={
            "file_name": "sample.png", "content_type": "image/png",
            "content_base64": base64.b64encode(image).decode(), "sha256": hashlib.sha256(image).hexdigest()})
        assert image_response.status_code == 200, image_response.text
        image_saved = image_response.json()
        assert image_saved["processing_status"] == "stored_image_not_parsed"
        assert image_saved["canonical_text"] is None
        stop(process)
        process = start()
        restored = client.get(path)
        assert restored.status_code == 200
        assert {item["attachment_id"] for item in restored.json()["items"]} == {saved["attachment_id"], image_saved["attachment_id"]}
        download = client.get(saved["download_path"])
        assert download.status_code == 200 and download.content == canonical_bytes
        assert client.get(image_saved["download_path"]).content == image
        backup = client.get(f"/api/workbench/cases/{case.project_id}/export")
        assert backup.status_code == 200
        assert saved["file_name"] in backup.text and image_saved["file_name"] in backup.text
        other = {"X-Service-Tenant-ID": "other_tenant", "X-Service-Auth": other_secret}
        provider_content = f"/api/data/attachments/{saved['attachment_id']}/content"
        assert httpx.get(base + provider_content, headers=headers, timeout=5).content == canonical_bytes
        assert httpx.get(base + provider_content, headers=other, timeout=5).status_code == 404
        assert httpx.get(base + provider_content, timeout=5).status_code == 401
        assert httpx.get(base + provider_content, headers={"X-Service-Auth": secret}, timeout=5).status_code == 403
        assert httpx.get(base + provider_content, headers={"X-Service-Tenant-ID": "test_tenant"}, timeout=5).status_code == 401
    finally:
        stop(process)
