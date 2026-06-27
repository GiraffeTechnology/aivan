"""Unit tests for the standalone GLTG API client.

These use an httpx MockTransport so no live GLTG server is required.
"""

from __future__ import annotations

import httpx
import pytest

from aivan.integrations.gltg_client import GLTGClient, GLTGClientResult


def _handler(captured: dict):
    def handle(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content"] = request.content.decode() if request.content else ""
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "gltg"})
        if request.url.path == "/v1/lead-time/estimate":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "estimated_lead_time_days": 28,
                    "earliest_delivery_date": "2026-07-25",
                    "feasible": True,
                    "supplier_count": 1,
                    "selected_supplier_id": "M1",
                    "warnings": [],
                    "calculation_trace": [],
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    return handle


def _client(captured: dict) -> GLTGClient:
    return GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(_handler(captured)))


def test_health_ok():
    cap: dict = {}
    res = _client(cap).health()
    assert res.ok is True
    assert res.data == {"status": "ok", "service": "gltg"}
    assert cap["method"] == "GET"


def test_estimate_lead_time_posts_payload():
    cap: dict = {}
    res = _client(cap).estimate_lead_time(
        order={"quantity": 10000, "product_type": "apparel"},
        suppliers=[{"supplier_id": "M1", "production_days": 14}],
    )
    assert res.ok is True
    assert res.data["estimated_lead_time_days"] == 28
    assert cap["method"] == "POST"
    assert "10000" in cap["content"]


def test_invalid_order_is_rejected_before_request():
    cap: dict = {}
    res = _client(cap).estimate_lead_time(order={}, suppliers=[])
    assert res.ok is False
    assert "quantity" in (res.error or "")
    # request never sent
    assert cap == {}


def test_http_error_surfaces_structured_error():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(handle))
    res = client.estimate_lead_time(order={"quantity": 1}, suppliers=[])
    assert res.ok is False
    assert res.status_code == 500
    assert "HTTP 500" in (res.error or "")


def test_connection_error_does_not_fall_back():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = GLTGClient(base_url="http://gltg.test", transport=httpx.MockTransport(handle))
    res = client.health()
    assert isinstance(res, GLTGClientResult)
    assert res.ok is False
    assert res.data is None  # never a locally computed value
