from __future__ import annotations
import os
import logging
from aivan.observability.safe_logging import log_exception_safely
import httpx
from aivan.governance.runtime_policy import is_production
from aivan.openclaw.contracts import OpenClawSendRequest, OpenClawSendResponse
from aivan.utils.time_utils import utcnow_iso

logger = logging.getLogger(__name__)

class OpenClawClient:
    def __init__(self):
        self.base_url = os.environ.get("OPENCLAW_BASE_URL", "")
        self.api_key = os.environ.get("OPENCLAW_API_KEY", "")
        self.mock_mode = os.environ.get("OPENCLAW_MOCK_MODE", "true").lower() == "true"
        if self.mock_mode and is_production():
            raise RuntimeError("OPENCLAW_MOCK_FORBIDDEN")
        self.timeout = 30

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-OpenClaw-Key"] = self.api_key
        return h

    def send_message(self, request: OpenClawSendRequest) -> OpenClawSendResponse:
        if self.mock_mode:
            # A simulation is not a transport acknowledgement. Callers persist
            # sent only on success; never let a mock create that business fact.
            return OpenClawSendResponse(
                success=False,
                outcome_uncertain=False,
                error="OPENCLAW_MOCK_MODE_NOT_SENT",
            )
        if not self.base_url:
            return OpenClawSendResponse(success=False, error="OPENCLAW_BASE_URL not configured")
        try:
            endpoint = os.environ.get("OPENCLAW_SEND_ENDPOINT", "/messages/send")
            resp = httpx.post(
                f"{self.base_url}{endpoint}",
                json=request.model_dump(),
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or type(data.get("success")) is not bool:
                raise ValueError("Missing explicit transport acknowledgement")
            if data["success"] and not (isinstance(data.get("message_id"), str) and data["message_id"].strip()):
                raise ValueError("Missing transport message identifier")
            return OpenClawSendResponse(
                success=data["success"], message_id=data.get("message_id", ""),
                sent_at=data.get("sent_at", utcnow_iso()),
                error=None if data["success"] else "Outbound transport rejected the request",
            )
        except httpx.HTTPStatusError as exc:
            uncertain = not (400 <= exc.response.status_code < 500)
            return OpenClawSendResponse(success=False, outcome_uncertain=uncertain,
                                       error="Outbound delivery is unconfirmed" if uncertain else "Outbound transport rejected the request")
        except Exception:
            # A lost response does not establish that the remote side rejected it.
            return OpenClawSendResponse(success=False, outcome_uncertain=True,
                                       error="Outbound delivery is unconfirmed")

    def check_account_status(self, account_connection_id: str) -> dict:
        if self.mock_mode:
            return {"status": "mock", "account_connection_id": account_connection_id,
                    "error": "OPENCLAW_MOCK_MODE_NOT_CONNECTED"}
        if not self.base_url:
            return {"status": "error", "error": "OPENCLAW_BASE_URL not configured"}
        try:
            resp = httpx.get(f"{self.base_url}/accounts/{account_connection_id}", headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            error_id = log_exception_safely(logger, "OpenClaw account status failed", exc=exc)
            return {"status": "error", "error": f"OPENCLAW_REQUEST_FAILED:{error_id}"}

_client: OpenClawClient | None = None

def get_openclaw_client() -> OpenClawClient:
    global _client
    if _client is None:
        _client = OpenClawClient()
    return _client
