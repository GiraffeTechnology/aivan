from __future__ import annotations
import os
import httpx
from aiven.openclaw.contracts import OpenClawSendRequest, OpenClawSendResponse
from aiven.utils.time_utils import utcnow_iso

class OpenClawClient:
    def __init__(self):
        self.base_url = os.environ.get("OPENCLAW_BASE_URL", "")
        self.api_key = os.environ.get("OPENCLAW_API_KEY", "")
        self.mock_mode = os.environ.get("OPENCLAW_MOCK_MODE", "true").lower() == "true"
        self.timeout = 30

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-OpenClaw-Key"] = self.api_key
        return h

    def send_message(self, request: OpenClawSendRequest) -> OpenClawSendResponse:
        if self.mock_mode:
            return OpenClawSendResponse(
                success=True,
                message_id=f"mock_msg_{request.conversation_id}_{utcnow_iso()}",
                sent_at=utcnow_iso(),
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
            return OpenClawSendResponse(
                success=data.get("success", True),
                message_id=data.get("message_id", ""),
                sent_at=data.get("sent_at", utcnow_iso()),
            )
        except Exception as e:
            return OpenClawSendResponse(success=False, error=str(e))

    def check_account_status(self, account_connection_id: str) -> dict:
        if self.mock_mode:
            return {"status": "connected", "account_connection_id": account_connection_id}
        if not self.base_url:
            return {"status": "error", "error": "OPENCLAW_BASE_URL not configured"}
        try:
            resp = httpx.get(f"{self.base_url}/accounts/{account_connection_id}", headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

_client: OpenClawClient | None = None

def get_openclaw_client() -> OpenClawClient:
    global _client
    if _client is None:
        _client = OpenClawClient()
    return _client
