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
                "case_id": body["case_id"],
                "quote_id": body["quote_id"],
                "actor_id": request.headers.get("X-AIVAN-Actor-ID"),
                "actor_role": request.headers.get("X-AIVAN-Role"),
                "sku": body["sku"],
                "supplier_id": body.get("supplier_id"),
                "supplier_quote": body["supplier_quote"],
                "currency": body.get("currency", "USD"),
                "quantity": body.get("quantity"),
                "buyer_unit_price": body["buyer_unit_price"],
                "buyer_total": body["buyer_total"],
                "supplier_total": body["supplier_total"],
                "margin_rate": body["margin_rate"],
                "gltg_run_id": body.get("gltg_run_id"),
                "gltg_api_version": body.get("gltg_api_version"),
                "quote_position": "within_mid_range",
                "recommendation": "negotiate",
                "confidence": "low",
                "human_approval_required": True,
                "approval_status": "pending",
                "dispatched": False,
                "llm_reasoning": "{}",
                "evidence_ids": "[]",
                "notes": body.get("notes"),
                "model_result": {
                    "quote_position": "within_mid_range",
                    "recommendation": "negotiate",
                    "confidence": "low",
                    "reasoning": "contract fixture",
                },
                "lineage": {
                    "source_trace_id": request.headers.get("X-AIVAN-Trace-ID"),
                    "case_id": body["case_id"],
                    "quote_id": body["quote_id"],
                    "supplier_id": body.get("supplier_id"),
                    "gltg_run_id": body.get("gltg_run_id"),
                    "gltg_api_version": body.get("gltg_api_version"),
                },
            },
        )

    return httpx.MockTransport(handler)
