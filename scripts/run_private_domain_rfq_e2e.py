#!/usr/bin/env python3
"""Private-domain RFQ E2E smoke (no external model API).

Drives the RFQ execution loop end-to-end with external model APIs OFF, proving
the baseline closes (or safely asks for confirmation) without any external
provider call. Uses the mock provider as a stand-in local model and the GLTG
fake transport for offline runs.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ.setdefault("AIVAN_EXTERNAL_MODEL_API_ENABLED", "false")
os.environ.setdefault("AIVAN_LLM_PROVIDER", "mock")
os.environ.setdefault("OPENCLAW_MOCK_MODE", "true")
os.environ.setdefault("AIVAN_DB_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from aivan.db.models import Base  # noqa: E402
from aivan.execution.rfq_execution import create_rfq_from_event  # noqa: E402
from aivan.integrations import gltg_client as _gltg_client  # noqa: E402
from aivan.openclaw.contracts import OpenClawEvent  # noqa: E402


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def main() -> int:
    # Offline GLTG fake so this runs without a live GLTG server.
    try:
        from tests.gltg_fake import mock_transport

        _gltg_client.set_default_transport(mock_transport())
    except Exception:
        pass

    db = _session()
    event = OpenClawEvent(
        source="openclaw",
        channel="wechat",
        conversation_id="pd_e2e_conv_001",
        message_id="pd_e2e_msg_001",
        sender_id="user_001",
        sender_display_name="Operator",
        message_text="帮我询价 10000 件白色纯棉衬衣，45 天内交温哥华，高品质。",
        role_context="user",
        mode="command",
    )
    result = create_rfq_from_event(event, db)
    print("action:", result.action)
    print("drafts_created:", result.drafts_created)
    print("operator_reply:\n" + result.user_control_message)

    assert "draft_" not in result.user_control_message, "raw draft ids leaked into reply"
    assert "Strategy=" not in result.user_control_message
    print("\n[OK] private-domain RFQ loop closed without external model API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
