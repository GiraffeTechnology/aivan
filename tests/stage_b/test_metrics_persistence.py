from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request


def test_failed_requests_are_counted_when_call_next_raises():
    from aivan.observability import metrics

    metrics._reset_metrics_for_tests()
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/boom",
            "raw_path": b"/boom",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )

    async def raises(_request):
        raise RuntimeError("downstream provider secret")

    with pytest.raises(RuntimeError, match="downstream provider secret"):
        asyncio.run(metrics.record_request_metrics(request, raises))

    rendered = metrics._render_metrics()
    assert (
        'aivan_http_requests_total{method="POST",route="unmatched",status_class="5xx"} 1'
        in rendered
    )
    assert "downstream provider secret" not in rendered
