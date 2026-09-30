"""Faithful no-network fixture for the Stage 1 GPM guidance surface."""

from __future__ import annotations

import hashlib

import httpx


def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != "/api/gpm/quote-guidance":
            return httpx.Response(404, json={"error": "not_found"})
        body = __import__("json").loads(request.content)
        tenant_id = request.headers.get("X-AIVAN-Tenant-ID", "")
        key = request.headers.get("Idempotency-Key", "")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return httpx.Response(
            201,
            json={
                "packet_id": f"gpm_pkt_{digest}",
                "tenant_id": tenant_id,
                "sku": body["sku"],
                "supplier_id": body.get("supplier_id"),
                "supplier_quote": body["supplier_quote"],
                "currency": body.get("currency", "USD"),
                "quantity": body.get("quantity"),
                "quote_position": "within_mid_range",
                "recommendation": "negotiate",
                "confidence": "low",
                "human_approval_required": True,
                "approval_status": "pending",
                "dispatched": False,
                "llm_reasoning": "{}",
                "evidence_ids": "[]",
                "notes": body.get("notes"),
            },
        )

    return httpx.MockTransport(handler)
