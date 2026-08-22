from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

from aivan.api.main import unhandled_exception_handler
from aivan.observability.safe_logging import log_exception_safely


def test_safe_exception_log_omits_message_traceback_and_payload(caplog):
    secret = "Authorization: Bearer raw-secret-token"
    caplog.set_level(logging.ERROR)

    error_id = log_exception_safely(
        logging.getLogger("aivan.test.safe"),
        "Dependency failed",
        exc=RuntimeError(secret),
        context={"operation": "fetch"},
    )

    rendered = caplog.text
    assert error_id in rendered
    assert "RuntimeError" in rendered
    assert "operation=fetch" in rendered
    assert secret not in rendered
    assert "Traceback" not in rendered


@pytest.mark.asyncio
async def test_api_exception_handler_never_logs_raw_exception(caplog):
    secret = "remote response body includes customer@example.com and token-123"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/invoke",
            "headers": [],
        }
    )
    caplog.set_level(logging.ERROR, logger="aivan.api")

    response = await unhandled_exception_handler(request, RuntimeError(secret))

    assert response.status_code == 200
    assert secret not in response.body.decode("utf-8")
    assert secret not in caplog.text
    assert "Traceback" not in caplog.text
