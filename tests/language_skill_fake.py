"""Synthetic English normalization contract for unrelated offline unit tests.

This fixture assumes each input is already English; it does not identify or
translate any language. Language-boundary tests install explicit responses or
failures. It is not evidence that a deployed detector or model works.
"""
import json

import httpx


def mock_transport() -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/language/canonical-db/validate":
            # Assumed English fixture, not real statistical identification.
            return httpx.Response(200, json={"valid": True, "violations": []})
        if request.url.path == "/v1/inbound/normalize":
            body = json.loads(request.content)
            return httpx.Response(200, json={
                "raw_text": body["source_text"],
                "canonical_text": body["source_text"],
                "canonical_language": "en",
                "language": {"detected": "en", "confidence": 1.0},
                "translation": {"provider": "synthetic-unit-fixture", "model": "english-fixture"},
                "field_evidence": {}, "warnings": [],
            })
        if request.url.path == "/v1/structure/rfq":
            return httpx.Response(200, json={"structured": {}, "validation_status": "incomplete"})
        return httpx.Response(503)
    return httpx.MockTransport(handle)
